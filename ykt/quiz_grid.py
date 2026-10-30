"""A4 grid settings and lossless in-memory Pillow/img2pdf page composition."""
import hashlib
import io
import json
import math
import os
import struct
from dataclasses import dataclass

from PIL import Image, ImageOps
from pypdf import PdfReader
from pypdf.generic import ContentStream

from .answer_images import pdf_field
from .browser import Stopped, check_stop
from .files import FileProblem

# All physical defaults live here. Changing them changes the layout identity.
GRID_VERSION = 1
A4_PT = (595.275591, 841.889764)
MARGIN_MM = 10.0  # Equal margins on all four sides.
GAP_MM = 4.0  # Reduced by sqrt(capacity) to avoid crowding dense layouts.
BASE_DPI = 300  # Raised per page when necessary to retain source pixel detail.
MAX_PAGE_PIXELS = 48_000_000  # Bound one RGB canvas; never silently downsample.
PRESETS = {1: (1, 1), 2: (2, 1), 4: (2, 2), 6: (3, 2), 8: (4, 2), 12: (4, 3)}  # rows, columns in portrait
LAYOUT_CHOICES = {'单题一页': 1, '每页2张': 2, '每页4张': 4, '每页6张': 6, '每页8张': 8, '每页12张': 12,
                  '自定义行列': None}


def positive_integer(value):
    if isinstance(value, bool):
        raise ValueError('行数和列数必须为正整数')
    text = str(value).strip()
    if not text.isascii() or not text.isdigit():
        raise ValueError('行数和列数必须为正整数，例如2和3')
    try:
        number = int(text)
        if number > 0:
            return number
    except ValueError:
        pass
    raise ValueError('行数和列数必须为正整数')


def normalize_layout(value):
    if value is None:
        return None  # Compatibility for existing non-GUI consumers/old records.
    if not isinstance(value, dict) or value.get('orientation', 'portrait') not in ('portrait', 'landscape'):
        raise ValueError('纸张方向必须为纵向或横向')
    orientation = value.get('orientation', 'portrait')
    mode = value.get('mode', 'preset')
    if mode == 'preset':
        count = positive_integer(value.get('count', 1))
        if count not in PRESETS:
            raise ValueError('请选择有效的每页题数或自定义行列')
        rows, columns = PRESETS[count]
        if orientation == 'landscape':
            rows, columns = columns, rows
    elif mode == 'custom':
        rows, columns = positive_integer(value.get('rows')), positive_integer(value.get('columns'))
        count = rows * columns
    else:
        raise ValueError('请选择有效的排版模式')
    spec = dict(version=GRID_VERSION, orientation=orientation, mode=mode, count=count,
                rows=rows, columns=columns, margin_mm=MARGIN_MM, gap_mm=GAP_MM, base_dpi=BASE_DPI)
    geometry(spec)  # Reject physically impossible density before a worker starts.
    return spec


def page_size(spec):
    return A4_PT if spec['orientation'] == 'portrait' else A4_PT[::-1]


def geometry(spec):
    width, height = page_size(spec)
    if spec['columns'] > int(width) or spec['rows'] > int(height):
        raise ValueError('行列过密，请减少行数或列数')
    margin = spec['margin_mm'] * 72 / 25.4
    gap = spec['gap_mm'] * 72 / 25.4 / math.sqrt(spec['count'])
    cell_w = (width - margin*2 - gap*(spec['columns']-1)) / spec['columns']
    cell_h = (height - margin*2 - gap*(spec['rows']-1)) / spec['rows']
    if min(cell_w, cell_h) < 1:
        raise ValueError('行列过密，单元格不足1磅，请减少行数或列数')
    return width, height, margin, gap, cell_w, cell_h


def layout_id(spec):
    return hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:16]


def field_for(options):
    base = pdf_field(options)
    spec = normalize_layout(options.get('quiz_layout'))
    return base if spec is None else base + '|grid|' + layout_id(spec)


def layout_suffix(spec):
    if spec is None:
        return ''
    text = '_{}{}题每页'.format('竖版' if spec['orientation'] == 'portrait' else '横版', spec['count'])
    if spec['mode'] == 'custom':
        text += '_{}行{}列'.format(spec['rows'], spec['columns'])
    return text


def grid_fingerprint(source, spec):
    return hashlib.sha256(json.dumps(dict(source=source, layout=spec), sort_keys=True).encode()).hexdigest()


def png_idat(data):
    """img2pdf embeds RGB PNG IDAT bytes directly; retain their exact digest."""
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise FileProblem('网格页面PNG编码无效')
    chunks, offset = [], 8
    while offset+12 <= len(data):
        length = struct.unpack('>I',data[offset:offset+4])[0]
        if data[offset+4:offset+8] == b'IDAT':
            chunks.append(data[offset+8:offset+8+length])
        offset += length+12
    if not chunks:
        raise FileProblem('网格页面PNG缺少像素流')
    return b''.join(chunks)


def placements(spec, sizes):
    """Place only actual questions; center occupied rows, including a short row."""
    width, height, margin, gap, cell_w, cell_h = geometry(spec)
    used_rows = math.ceil(len(sizes) / spec['columns'])
    top = (height - used_rows*cell_h - (used_rows-1)*gap) / 2
    boxes = []
    for index, (iw, ih) in enumerate(sizes):
        row, column = divmod(index, spec['columns'])
        row_count = min(spec['columns'], len(sizes)-row*spec['columns'])
        left = (width - row_count*cell_w - (row_count-1)*gap) / 2
        scale = min(cell_w/iw, cell_h/ih)
        w, h = iw*scale, ih*scale
        boxes.append((left + column*(cell_w+gap)+(cell_w-w)/2,
                      top + row*(cell_h+gap)+(cell_h-h)/2, w, h))
    return boxes


@dataclass
class GridPage:
    sources: object
    spec: dict
    stop: object
    checks: list
    notes: list

    def read_bytes(self):
        sizes = []
        for source in self.sources:
            check_stop(self.stop)
            with Image.open(io.BytesIO(source.read_bytes())) as image:
                if getattr(image, 'n_frames', 1) != 1:
                    raise FileProblem('多帧习题图片无法可靠排版')
                sizes.append(ImageOps.exif_transpose(image).size)
        boxes = placements(self.spec, sizes)
        # Preserve input detail instead of using a fixed low-resolution canvas.
        dpi = max(self.spec['base_dpi'], math.ceil(max(
            max(iw*72/w, ih*72/h) for (iw, ih), (_, _, w, h) in zip(sizes, boxes))))
        pt_w, pt_h = page_size(self.spec)
        width, height = math.ceil(pt_w*dpi/72), math.ceil(pt_h*dpi/72)
        if width*height > MAX_PAGE_PIXELS:
            raise FileProblem('保持原图画质所需的单页像素超出预算，请减少行列数或每页题数')
        canvas = Image.new('RGB', (width, height), 'white')
        try:
            for index,(source, size, (x, y, w, h)) in enumerate(zip(self.sources, sizes, boxes),1):
                check_stop(self.stop)
                with Image.open(io.BytesIO(source.read_bytes())) as image:
                    if 'A' in image.getbands() or 'transparency' in image.info:
                        self.notes.append('网格第{}页第{}题：透明通道合成白底'.format(len(self.checks)+1,index))
                    if image.getexif().get(274,1)!=1:
                        self.notes.append('网格第{}页第{}题：按EXIF方向旋转'.format(len(self.checks)+1,index))
                    rgba = ImageOps.exif_transpose(image).convert('RGBA')
                    rgb = Image.new('RGB', rgba.size, 'white')
                    rgb.paste(rgba, mask=rgba.getchannel('A'))
                    # One scale factor; contain() never crops or distorts.
                    resized = ImageOps.contain(rgb, (max(size[0], round(w*dpi/72)),
                        max(size[1], round(h*dpi/72))), Image.Resampling.LANCZOS)
                    px, py = round(x*dpi/72), round(y*dpi/72)
                    canvas.paste(resized, (px, py))
                    resized.close(); rgb.close(); rgba.close()
            check_stop(self.stop)
            buffer = io.BytesIO()
            canvas.save(buffer, format='PNG')  # Lossless; never intermediate image files.
            data = buffer.getvalue()
            self.checks.append(dict(width=width, height=height,
                sha256=hashlib.sha256(canvas.tobytes()).hexdigest(), questions=len(self.sources),
                encoded_sha256=hashlib.sha256(png_idat(data)).hexdigest()))
            self.notes.append('网格第{}页：{}题，{}×{}像素，{}DPI，PNG无损'.format(
                len(self.checks), len(self.sources), width, height, dpi))
            check_stop(self.stop)
            return data
        finally:
            canvas.close()


def write_grid_pdf(path, sources, stop, spec):
    import img2pdf
    checks, notes = [], []
    pages = [GridPage(sources[i:i+spec['count']], spec, stop, checks, notes)
             for i in range(0, len(sources), spec['count'])]
    if not pages:
        raise FileProblem('无习题图片，不生成空PDF')
    width, height = page_size(spec)
    with path.open('xb') as stream:
        img2pdf.convert(pages, outputstream=stream, engine=img2pdf.Engine.internal,
            nodate=True, layout_fun=lambda *_: (width, height, width, height))
        check_stop(stop)
        stream.flush(); os.fsync(stream.fileno())
    return notes, checks


def validate_grid_pdf(path, pages, spec, checks, stop=None):
    try:
        if len(checks) != pages or pages < 1:
            return False
        with path.open('rb') as stream:
            reader = PdfReader(stream, strict=True)
            if reader.is_encrypted or len(reader.pages) != pages:
                return False
            for page, expected in zip(reader.pages, checks):
                if stop is not None:
                    check_stop(stop)
                if any(abs(float(a)-b)>.02 for a,b in zip(
                        (page.mediabox.width,page.mediabox.height),page_size(spec))):
                    return False
                ops = ContentStream(page.get_contents(),reader).operations
                if [op for _,op in ops] != [b'q',b'cm',b'Do',b'Q']:
                    return False
                w,b,c,h,x,y = [float(v) for v in ops[1][0]]
                if b or c or x or y or abs(w-page_size(spec)[0])>.02 or abs(h-page_size(spec)[1])>.02:
                    return False
                objects = page['/Resources']['/XObject'].get_object()
                if len(objects)!=1 or ops[2][0][0] not in objects:
                    return False
                image = objects[ops[2][0][0]].get_object()
                if (image.get('/Subtype')!='/Image' or image.get('/Width')!=expected['width'] or
                    image.get('/Height')!=expected['height'] or expected['width']*expected['height']>MAX_PAGE_PIXELS or
                    image.get('/ColorSpace')!='/DeviceRGB' or image.get('/BitsPerComponent')!=8 or
                    image.get('/Filter')!='/FlateDecode' or '/SMask' in image):
                    return False
                parameters = image.get('/DecodeParms',{}).get_object()
                if (parameters.get('/Predictor')!=15 or parameters.get('/Columns')!=expected['width'] or
                    parameters.get('/Colors')!=3 or parameters.get('/BitsPerComponent',8)!=8):
                    return False
                # Verify copied compressed PNG bytes, without changing pypdf's
                # global decompression safeguards (a 12-up page can exceed its
                # default 75MB decoded stream limit).
                if hashlib.sha256(image._data).hexdigest()!=expected['encoded_sha256']:
                    return False
            return True
    except Stopped:
        raise
    except Exception:
        return False
