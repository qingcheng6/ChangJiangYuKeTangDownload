"""In-memory answer labels; never writes or changes the original image."""
import io
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .files import FileProblem

ANNOTATION_VERSION = 2
ANSWER_FIELD = 'quiz_pdf_answers'


def pdf_field(options):
    return ANSWER_FIELD if options.get('quiz_answers') else 'quiz_pdf'


def annotated_fingerprint(source, identity):
    return hashlib.sha256(json.dumps(dict(source=source, annotation_version=ANNOTATION_VERSION,
        answers=identity), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def normalize_choice(text):
    if not isinstance(text, str):
        return None
    text = unicodedata.normalize('NFKC', text).strip()
    if not re.fullmatch(r'[A-Z](?:[A-Z\s,，、/;；]*[A-Z])?', text):
        return None
    letters = re.sub(r'[\s,，、/;；]', '', text)
    if not letters or len(letters) > 26 or letters in ('TRUE', 'FALSE', 'YES', 'NO', 'NONE', 'NULL'):
        return None
    return ''.join(dict.fromkeys(letters))


def read_native_answer(text):
    """Only explicit correct/reference labels; submitted choices are excluded.

    The actual report currently inspected exposes submitted answers only.
    This positive label grammar has local tests, not a live-positive claim.
    """
    values = []
    for line in text.splitlines():
        match = re.fullmatch(r'\s*(?:正确答案|参考答案)\s*[:：]\s*(.*?)\s*', line)
        if match:
            choice = normalize_choice(match.group(1))
            if choice:
                values.append(choice)
    values = list(dict.fromkeys(values))
    if len(values) == 1:
        return dict(answer=values[0], source='correct_dom', status='available', reason=None)
    return dict(answer=None, source='correct_dom', status='missing',
                reason='多个答案字段不一致，未猜测' if values else '未显示可识别的正确/参考答案')


def missing_answer(reason):
    # Stable state for later answer providers; no AI provider is implemented.
    return dict(answer=None, source='none', status='missing', confidence='none',
                reason_code='no_usable_correct_answer', reason=reason)


def full_score(value):
    if not isinstance(value,str):
        return False
    parts=unicodedata.normalize('NFKC',value).strip().split('/')
    if len(parts)!=2 or any(not re.fullmatch(r'\d+(?:\.\d+)?',p.strip()) for p in parts):
        return False
    try:
        actual,total=(Decimal(p.strip()) for p in parts)
        return total>0 and actual==total
    except InvalidOperation:
        return False


def infer_submission(evidence):
    if not isinstance(evidence,dict) or evidence.get('visible') is not True:
        return missing_answer('提交结果区域缺失或不可见')
    classes=evidence.get('classes')
    if (not isinstance(classes,list) or 'green' not in classes or 'red' in classes or
            evidence.get('color')!='rgb(8, 188, 114)'):
        return missing_answer('提交选项不是已验证的绿色样式')
    choice=normalize_choice(evidence.get('submitted'))
    if choice is None or choice!=normalize_choice(evidence.get('result_text')):
        return missing_answer('提交选项字母缺失或与结果元素不一致')
    if not full_score(evidence.get('score')):
        return missing_answer('该题得分缺失、格式无效或未满分')
    return dict(answer=choice, source='submission_verified', status='available',
                confidence='verified_submission', reason=None, evidence=dict(evidence))


def select_answer(text, evidence=None):
    native=read_native_answer(text)
    if native['answer'] is not None:
        return dict(native,confidence='official')
    return infer_submission(evidence)


def trusted_answer(mapping):
    answer=normalize_choice(mapping.get('answer'))
    if mapping.get('status')!='available' or answer is None or answer!=mapping.get('answer'):
        return False
    if mapping.get('source')=='correct_dom':
        return True
    if mapping.get('source')=='submission_verified' and mapping.get('confidence')=='verified_submission':
        inferred=infer_submission(mapping.get('evidence'))
        return inferred['answer']==answer and inferred['status']=='available'
    return False


def _font(size):
    # Pillow searches the Windows Fonts directory; no font download is needed.
    for name in ('arialbd.ttf', 'msyhbd.ttc', 'DejaVuSans-Bold.ttf'):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def annotate_bytes(data, answer):
    answer = normalize_choice(answer)
    if answer is None:
        return data
    with Image.open(io.BytesIO(data)) as source:
        if getattr(source, 'n_frames', 1) != 1:
            raise FileProblem('多帧图片无法可靠标注答案')
        rgba = ImageOps.exif_transpose(source).convert('RGBA')
        original = Image.new('RGB', rgba.size, 'white')
        original.paste(rgba, mask=rgba.getchannel('A'))
    width, height = original.size
    padding = max(2, round(width * .015))
    size = max(8, round(width * .075))
    measure = ImageDraw.Draw(original)
    while True:
        font = _font(size)
        stroke = max(1, round(size * .035))
        bounds = measure.textbbox((0, 0), answer, font=font, stroke_width=stroke)
        text_width, text_height = bounds[2]-bounds[0], bounds[3]-bounds[1]
        if text_width + padding*2 <= width:
            break
        size -= 1
        if size < 4:
            raise FileProblem('图片过窄，无法在不遮挡内容的情况下标注答案')
    band = text_height + padding*2
    canvas = Image.new('RGBA', (width, height+band), 'white')
    canvas.paste(original, (0, 0))
    overlay = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    left = width-text_width-padding*2
    # The panel is wholly below the original pixels, even for questions which
    # fill the lower-right corner. The label is not a destructive overlay.
    draw.rounded_rectangle((left, height, width-1, height+band-1), radius=max(1, padding//2), fill=(0, 0, 0, 215))
    draw.text((width-padding-text_width-bounds[0], height+padding-bounds[1]), answer,
              font=font, fill='white', stroke_width=stroke, stroke_fill='black')
    result = Image.alpha_composite(canvas, overlay).convert('RGB')
    buffer = io.BytesIO()
    result.save(buffer, format='PNG')
    return buffer.getvalue()


@dataclass(frozen=True)
class AnswerImage:
    path: object
    answer: str

    def read_bytes(self):
        return annotate_bytes(self.path.read_bytes(), self.answer)


def annotated_sources(paths, sequence, mappings):
    if not isinstance(mappings, list) or len(mappings) != len(sequence) or len(paths) != len(sequence):
        raise FileProblem('网页答案映射缺失或数量不匹配，未生成可能错位的标注PDF')
    output, identity, marked = [], [], 0
    for index, (path, occurrence, mapping) in enumerate(zip(paths, sequence, mappings)):
        if (not isinstance(mapping, dict) or mapping.get('occurrence') != index or
                any(mapping.get(k) != occurrence[k] for k in ('resource_id', 'slide_id', 'page'))):
            raise FileProblem('答案与习题图片顺序不匹配，未生成可能错位的标注PDF')
        answer = normalize_choice(mapping.get('answer')) if mapping.get('status') == 'available' else None
        if answer is not None and not trusted_answer(mapping):
            raise FileProblem('答案来源尚未验证，未标注')
        output.append(AnswerImage(path, answer) if answer else path)
        identity.append(dict(occurrence, answer=answer, source=mapping.get('source'),
                             status='available' if answer else 'missing',
                             confidence=('official' if mapping.get('source')=='correct_dom' else mapping.get('confidence')) if answer else 'none',
                             **({'evidence':mapping['evidence']} if answer and mapping.get('source')=='submission_verified' else {})))
        marked += int(answer is not None)
    return output, identity, dict(annotated_pages=marked, missing_answers=len(sequence)-marked)
