"""Local A4 image PDFs, verified against ordered source hashes before commit."""
import hashlib
import io
import json
import os
import re
import uuid
import zlib
from pathlib import Path

from PIL import Image, ImageOps
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (ContentStream, DecodedStreamObject, DictionaryObject,
                          EncodedStreamObject, NameObject, NumberObject)

from .browser import Stopped, check_stop
from .files import FileProblem, image_info, safe_name, safe_prefixed_name, units
from .naming import lesson_key, named
from .answer_images import (ANNOTATION_VERSION, ANSWER_FIELD, annotated_sources,
                           annotated_fingerprint, normalize_choice)

A4 = (595.275591, 841.889764)
PDF_VERSION = 1


def sha_file(path, stop=None):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            if stop is not None:
                check_stop(stop)
            value.update(chunk)
    return value.hexdigest()


def image_stream(path):
    data = path.read_bytes()
    info = image_info(data)
    notes = []
    with Image.open(io.BytesIO(data)) as source:
        if getattr(source, "n_frames", 1) != 1:
            raise FileProblem("多帧图片无法确认静态展示页，未生成不完整合集")
        direct = source.format == "JPEG" and source.mode in ("RGB", "L") and source.getexif().get(274, 1) == 1
        if direct:
            width, height = source.size
            mode = source.mode
            payload = data
            filter_name = "/DCTDecode"
        else:
            image = ImageOps.exif_transpose(source)
            if source.getexif().get(274, 1) != 1:
                notes.append("按EXIF方向旋转")
            if "A" in image.getbands() or "transparency" in source.info:
                rgba = image.convert("RGBA")
                image = Image.new("RGB", rgba.size, "white")
                image.paste(rgba, mask=rgba.getchannel("A"))
                notes.append("透明通道合成白底")
            elif image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
                notes.append("颜色模式转换为RGB")
            width, height = image.size
            mode = image.mode
            payload = zlib.compress(image.tobytes())
            filter_name = "/FlateDecode"
            notes.append("{}解码后无损压缩，未降低像素尺寸".format(source.format))
    stream = EncodedStreamObject()
    stream._data = payload
    stream.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Image"),
        NameObject("/Width"): NumberObject(width), NameObject("/Height"): NumberObject(height),
        NameObject("/ColorSpace"): NameObject("/DeviceGray" if mode == "L" else "/DeviceRGB"),
        NameObject("/BitsPerComponent"): NumberObject(8), NameObject("/Filter"): NameObject(filter_name)})
    return stream, width, height, notes, info


def write_pdf(path, paths, stop, page_size=A4):
    writer = PdfWriter()
    conversions = []
    for index, source in enumerate(paths, 1):
        check_stop(stop)
        stream, width, height, notes, _ = image_stream(source)
        page = writer.add_blank_page(*page_size)
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/XObject"): DictionaryObject({
            NameObject("/Im0"): writer._add_object(stream)})})
        scale = min(page_size[0] / width, page_size[1] / height)
        w, h = width * scale, height * scale
        x, y = (page_size[0] - w) / 2, (page_size[1] - h) / 2
        content = DecodedStreamObject()
        content.set_data(("q %.7f 0 0 %.7f %.7f %.7f cm /Im0 Do Q\n" % (w, h, x, y)).encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(content)
        conversions.extend("第{}页：{}".format(index, note) for note in notes)
    check_stop(stop)
    with path.open("xb") as stream:
        writer.write(stream)
        stream.flush()
        os.fsync(stream.fileno())
    return conversions


def validate_pdf(path, pages, stop=None, page_size=A4):
    try:
        with path.open("rb") as stream:
            if not stream.read(8).startswith(b"%PDF-"):
                return False
            stream.seek(0)
            reader = PdfReader(stream, strict=True)
            if reader.is_encrypted or len(reader.pages) != pages or pages < 1:
                return False
            for page in reader.pages:
                if stop is not None:
                    check_stop(stop)
                if any(abs(float(size) - target) > 0.02 for size, target in zip(
                        (page.mediabox.width, page.mediabox.height), page_size)):
                    return False
                operations = ContentStream(page.get_contents(), reader).operations
                if [op for _, op in operations] != [b"q", b"cm", b"Do", b"Q"]:
                    return False
                matrix = [float(v) for v in operations[1][0]]
                w, b, c, h, x, y = matrix
                if b or c or w <= 0 or h <= 0 or min(x, y) < -0.01 or x + w > page_size[0] + 0.02 or y + h > page_size[1] + 0.02:
                    return False
                images = list(page.images)
                if len(images) != 1:
                    return False
                with Image.open(io.BytesIO(images[0].data)) as image:
                    image.load()
                    if abs(w / h - image.width / image.height) > 0.001:
                        return False
            return True
    except Stopped:
        raise
    except Exception:
        return False


def verified_pdf(manifest, metadata, stop=None, answers=False):
    try:
        path = manifest.resolve(metadata["path"])
        variant_ok = metadata.get('variant', 'plain') == 'plain'
        if answers:
            mapping = metadata.get('answer_mapping')
            variant_ok = (metadata.get('variant') == 'answers' and metadata.get('annotation_version') == ANNOTATION_VERSION
                and type(metadata.get('annotated_pages')) is int and metadata['annotated_pages'] >= 0
                and type(metadata.get('missing_answers')) is int and metadata['missing_answers'] >= 0
                and metadata['annotated_pages'] + metadata['missing_answers'] == metadata.get('pages')
                and isinstance(mapping, list) and len(mapping) == metadata.get('pages')
                and all(isinstance(row, dict) and (row.get('answer') is None or
                    (normalize_choice(row['answer']) == row['answer'] and row.get('source') == 'correct_dom'))
                    for row in mapping)
                and sum(row.get('answer') is not None for row in mapping) == metadata['annotated_pages']
                and isinstance(metadata.get('source_fingerprint'),str)
                and re.fullmatch(r'[0-9a-f]{64}',metadata['source_fingerprint']) is not None
                and annotated_fingerprint(metadata['source_fingerprint'],mapping) == metadata.get('fingerprint'))
        return (variant_ok and metadata["status"] == "complete" and metadata.get("version") == PDF_VERSION
            and isinstance(metadata.get("fingerprint"), str) and re.fullmatch(r"[0-9a-f]{64}", metadata["fingerprint"]) is not None
            and type(metadata.get("pages")) is int and metadata["pages"] > 0
            and path.suffix.lower() == ".pdf" and path.stat().st_size == metadata["size"]
            and sha_file(path, stop) == metadata["sha256"] and validate_pdf(path, metadata["pages"], stop))
    except (OSError, FileProblem, KeyError, TypeError, ValueError):
        return False


def ordered_sources(manifest, lesson):
    sequence = lesson.get("pdf_sequence")
    if lesson.get("status") != "complete" or lesson.get("warnings") or not sequence:
        raise FileProblem("习题图片未全部完成或缺少已验证页序，未生成PDF")
    if len({item["slide_id"] for item in sequence}) != lesson.get("quiz_pages"):
        raise FileProblem("习题页数与图片顺序记录不完整，未生成PDF")
    paths, identity = [], []
    for occurrence in sequence:
        record = lesson["resources"][occurrence["resource_id"]]
        if not manifest.verified(record):
            raise FileProblem("习题图片缺失、损坏或未完成，未生成PDF")
        paths.append(manifest.resolve(record["path"]))
        identity.append(dict(occurrence, sha256=record["sha256"]))
    fingerprint = hashlib.sha256(json.dumps(dict(version=PDF_VERSION, sequence=identity),
        sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return paths, fingerprint


def pdf_path(manifest, task, lesson, metadata, suffix="_习题合集.pdf"):
    parent = manifest.pdf_directory_for(task, lesson)
    if metadata.get("path"):
        existing = manifest.resolve(metadata["path"])
        if existing.parent != parent or existing.suffix.lower() != ".pdf":
            raise FileProblem("PDF任务路径与归档目录不匹配")
        return existing
    budget = min(80, 234 - units(parent) - units(suffix))
    if budget < 10:
        raise FileProblem("PDF文件路径过长，请选择较短保存目录")
    # The reserved lesson component also distinguishes same-name PDF-only
    # lessons, for which no image directory will ever be created.
    prefix = task.get('_naming', {}).get('prefix', '')
    label = Path(lesson["directory"]).name if manifest.layout == "flat" else named(task, task["lesson"]["name"])
    raw = label[len(prefix):] if prefix else label
    base = safe_prefixed_name(raw, prefix, budget)
    candidate = parent / (base + suffix)
    number = 0
    while candidate.exists():
        number += 1
        extra = "_" + hashlib.sha256((task["course_id"] + ":" + task["lesson"]["id"] + ":" + str(number)).encode()).hexdigest()[:8]
        raw_base = base[len(prefix):] if prefix else base
        candidate = parent / (safe_prefixed_name(raw_base, prefix, budget - len(extra)) + extra + suffix)
    manifest.resolve(str(candidate.relative_to(manifest.root)))
    return candidate


def merge_lesson(target, task, source, source_lesson, stop, emit, answers=False):
    """Caller holds the target Manifest lock; image status is never overwritten."""
    key = lesson_key(task)
    new = key not in target.data["lessons"]
    lesson = target.lesson(task)
    if new:
        lesson["status"] = "pdf_only"
    metadata = lesson.setdefault(ANSWER_FIELD if answers else "quiz_pdf", {})
    result = dict(status="running", resource_state="available" if source_lesson.get("quiz_pages", 0) > 0 else "unknown",
                  error=None, error_type=None)
    try:
        if source_lesson.get("status") == "no_images":
            metadata.update(status="no_images", pages=0, error=None, error_type=None)
            result.update(status="no_images", resource_state="absent")
            return result
        paths, fingerprint = ordered_sources(source, source_lesson)
        extra = {}
        if answers:
            paths, identity, stats = annotated_sources(paths, source_lesson['pdf_sequence'], source_lesson.get('native_answers'))
            source_fingerprint = fingerprint
            fingerprint = annotated_fingerprint(source_fingerprint,identity)
            extra = dict(variant='answers', annotation_version=ANNOTATION_VERSION, source_fingerprint=source_fingerprint,
                         answer_mapping=identity, **stats)
            for index, row in enumerate(identity, 1):
                if row['answer'] is None:
                    emit('第{}页：无答案，未标注'.format(index))
        result["resource_state"] = "available"
        if metadata.get("fingerprint") == fingerprint and verified_pdf(target, metadata, stop, answers=answers):
            result.update(metadata, skipped=True, error=None, error_type=None)
            emit("PDF完整、页序与来源一致，已跳过：" + metadata['path'])
            return result
        suffix = '_习题合集_带答案.pdf' if answers else '_习题合集.pdf'
        if metadata.get('path') and (metadata.get('variant', 'plain') != ('answers' if answers else 'plain') or
                (answers and not metadata['path'].endswith(suffix))):
            raise FileProblem('习题PDF版本与任务路径不匹配，原文件未修改')
        path = pdf_path(target, task, lesson, metadata, suffix=suffix)
        metadata.update(path=str(path.relative_to(target.root)), status="pending", fingerprint=fingerprint, **extra)
        target.save()
        path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(3):
            check_stop(stop)
            temporary = path.parent / (".pdf_" + uuid.uuid4().hex[:8] + ".part")
            target.resolve(str(temporary.relative_to(target.root)))
            metadata["attempts_last_run"] = attempt + 1
            try:
                conversions = write_pdf(temporary, paths, stop)
                if not validate_pdf(temporary, len(paths), stop):
                    raise FileProblem("PDF页数、页面或图片校验未通过")
                check_stop(stop)
                size, digest = temporary.stat().st_size, sha_file(temporary, stop)
                os.replace(str(temporary), str(path))
                metadata.update(status="complete", version=PDF_VERSION, pages=len(paths),
                    size=size, sha256=digest, conversions=conversions, error=None, error_type=None)
                result.update(metadata, skipped=False)
                for message in conversions:
                    emit("转换记录：" + message)
                emit("已保存习题合集，{}页：{}".format(len(paths), metadata['path']))
                if answers:
                    emit('答案标注{}页，无答案{}页；原图未修改'.format(metadata['annotated_pages'],metadata['missing_answers']))
                return result
            except Stopped:
                raise
            except Exception as exc:
                if attempt == 2:
                    raise FileProblem("PDF生成、校验或本地写入失败（{}），已重试2次".format(type(exc).__name__)) from None
                emit("PDF失败（{}），重试 {}/2".format(type(exc).__name__, attempt + 1))
                if stop.wait(attempt + 1):
                    raise Stopped()
            finally:
                if temporary.is_file():
                    temporary.unlink()
    except Stopped:
        metadata["status"] = "stopped"
        raise
    except Exception as exc:
        reason = str(exc) if isinstance(exc, FileProblem) else "PDF来源或任务记录异常"
        metadata.update(status="failed", error=reason, error_type=type(exc).__name__)
        result.update(status="failed", error=reason, error_type=type(exc).__name__)
        emit("PDF未完成：" + reason)
        return result
    finally:
        target.save()
