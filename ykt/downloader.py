"""Serial authenticated image download, local integrity-checked resume and stop."""

import base64
import hashlib
import os
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, unquote_to_bytes, urlsplit, urlunsplit

from playwright.sync_api import Error, TimeoutError

from .browser import NeedsHuman, PageChanged, Stopped, check_stop, ensure_login
from .extractor import extract_lesson
from .files import FileProblem, Manifest, image_info
from .scanner import course_catalog
from .naming import lesson_key


def resource_key(url):
    parts = urlsplit(url)
    if parts.scheme in ("data", "blob"):
        return hashlib.sha256(url.encode()).hexdigest()
    # Preserve content-identifying query fields, discard rotating authorization.
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not any(marker in k.lower() for marker in
                        ("auth", "token", "sign", "credential", "expires", "x-amz", "x-oss", "deadline"))]
    canonical = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path,
                            urlencode(sorted(query)), ""))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _fetch(context, resource, url, origin, stop):
    check_stop(stop)
    parts = urlsplit(url)
    if parts.scheme == "data":
        if len(url) > 90 * 1024 * 1024:
            raise FileProblem("内嵌图片过大")
        header, value = url.split(",", 1)
        try:
            return (base64.b64decode(value, validate=True) if ";base64" in header
                    else unquote_to_bytes(value))
        except (ValueError, TypeError):
            raise FileProblem("内嵌图片编码无效") from None
    if parts.scheme == "blob":
        value = resource["frame"].evaluate("""async url=>{
          const response=await fetch(url);if(!response.ok)throw Error('blob unavailable');
          const blob=await response.blob();if(blob.size>67108864)throw Error('blob too large');
          return await new Promise((resolve,reject)=>{
            const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);
            reader.onerror=reject;reader.readAsDataURL(blob);
          });
        }""", url)
        return base64.b64decode(value, validate=True)
    if parts.scheme not in ("http", "https") or parts.username or parts.password:
        raise FileProblem("图片资源入口不受支持")
    response = None
    try:
        response = context.request.get(url, headers={"Referer": origin + "/"},
                                       timeout=15000, max_redirects=3, max_retries=0)
        if response.status in (401, 403, 429):
            raise NeedsHuman("图片资源要求重新授权或限流处理；请人工检查后继续，程序将刷新报告资源")
        if response.status != 200:
            raise FileProblem("图片请求返回 HTTP {}".format(response.status))
        headers = response.headers
        if "text/html" in headers.get("content-type", "").lower():
            raise NeedsHuman("图片资源返回网页，请人工检查登录、权限或验证提示")
        declared = headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > 64 * 1024 * 1024:
            raise FileProblem("图片超过64MiB限制")
        data = response.body()
        check_stop(stop)
        if (declared and declared.isdigit() and not headers.get("content-encoding") and
                len(data) != int(declared)):
            raise FileProblem("图片响应长度不完整")
        return data
    finally:
        if response is not None:
            response.dispose()


def _atomic_image(manifest, path, record, data, stop):
    temporary = path.with_name(path.name + ".part")
    manifest.resolve(str(temporary.relative_to(manifest.root)))
    path.parent.mkdir(parents=True, exist_ok=True)
    record["path"] = str(path.relative_to(manifest.root))
    record["status"] = "pending"
    manifest.save()
    try:
        if temporary.exists() and not temporary.is_file():
            raise FileProblem("临时文件名被目录占用，请处理冲突或选择其他目录")
        with temporary.open("wb") as stream:
            for index in range(0, len(data), 65536):
                check_stop(stop)
                stream.write(data[index:index + 65536])
            stream.flush()
            os.fsync(stream.fileno())
        check_stop(stop)
        os.replace(str(temporary), str(path))
    finally:
        if temporary.is_file():
            temporary.unlink()  # Only our exact .part file inside the chosen root.


def verify_account(page, origin, owner, stop, emit):
    ensure_login(page, origin, stop, emit)
    current = course_catalog(page, stop)
    actual_owner = hashlib.sha256((origin + ":" + current["account"]).encode()).hexdigest()
    if actual_owner != owner:
        raise NeedsHuman("当前登录账号与课程缓存不一致，请停止并重新扫描，或切回原账号")


def download(context, page, origin, tasks, directory, owner, stop, emit, on_progress=None,
             on_lesson=None, layout="legacy", naming=None):
    verify_account(page, origin, owner, stop, emit)
    result = dict(total=len(tasks), completed=0, success=0, failed=0, status="running",
                  downloaded=0, skipped=0, image_failed=0, no_images=0,
                  current_course="—", current_lesson="—")

    def report():
        if on_progress is not None:
            on_progress(dict(result))

    with Manifest(directory, owner, origin, layout=layout) as manifest:
        started_tasks = set()
        report()
        try:
            for task in tasks:
                check_stop(stop)
                if naming:
                    naming.bind(task, emit)
                lesson = manifest.lesson(task)
                started_tasks.add(lesson_key(task))
                lesson["status"] = "running"
                lesson.pop("error", None)
                lesson.pop("error_type", None)
                result["current_course"] = task["course_name"]
                result["current_lesson"] = task["lesson"]["name"]
                manifest.save()
                if on_lesson is not None:
                    on_lesson(task, dict(lesson))
                report()
                emit("处理课时：{} / {}".format(" ".join(task["course_name"].split()),
                                               " ".join(task["lesson"]["name"].split())))
                try:
                    extracted = extract_lesson(page, origin, task, stop, emit)
                    lesson["warnings"] = list(dict.fromkeys(extracted["unsupported"]))
                    lesson["quiz_pages"] = extracted["pages"]
                    unique = []
                    seen = set()
                    # Keep display occurrences separately from the V1 resource
                    # de-duplication so a PDF never sorts filenames or loses a
                    # repeated image displayed on another question page.
                    lesson["pdf_sequence"] = [dict(resource_id=resource_key(r["candidates"][0]),
                        slide_id=r["slide_id"], page=r["page"]) for r in extracted["resources"]]
                    for resource in extracted["resources"]:
                        key = resource_key(resource["candidates"][0])
                        if key not in seen:
                            seen.add(key)
                            unique.append((key, resource))
                    if not unique and not lesson["warnings"]:
                        lesson["status"] = "no_images"
                        result["no_images"] += 1
                        result["success"] += 1
                        emit("本课时无习题图片，未创建课时目录")
                    else:
                        failed = 0
                        for order, (key, resource) in enumerate(unique, 1):
                            check_stop(stop)
                            record = lesson["resources"].setdefault(key, dict(
                                resource_id=key, status="pending", path=None))
                            record.update(order=order, slide_id=resource["slide_id"], page=resource["page"])
                            if manifest.verified(record):
                                result["skipped"] += 1
                                emit("图片 {}/{}：文件完整，已跳过 {}".format(order, len(unique), record['path']))
                                report()
                                continue
                            record["status"] = "pending"
                            record.pop("error", None)
                            manifest.save()
                            success = False
                            for attempt in range(3):  # Initial request + at most two retries per image.
                                check_stop(stop)
                                record["attempts_last_run"] = attempt + 1
                                record["attempts_total"] = record.get("attempts_total", 0) + 1
                                try:
                                    candidates = resource["candidates"]
                                    url = candidates[min(attempt, len(candidates) - 1)]
                                    data = _fetch(context, resource, url, origin, stop)
                                    info = image_info(data)
                                    duplicate = next((other for other in lesson["resources"].values()
                                                      if other is not record and other.get("sha256") == info["sha256"]
                                                      and manifest.verified(other)), None)
                                    if duplicate:
                                        record.update(info, status="duplicate", path=duplicate["path"],
                                                      duplicate_of=duplicate["resource_id"])
                                        result["skipped"] += 1
                                    else:
                                        path = manifest.output_path(task, lesson, record, info, order, key)
                                        _atomic_image(manifest, path, record, data, stop)
                                        record.update(info, status="complete")
                                        record.pop("duplicate_of", None)
                                        result["downloaded"] += 1
                                    record.pop("error", None)
                                    manifest.save()
                                    emit("图片 {}/{}：{}".format(order, len(unique),
                                         "相同内容已去重 " + record['path'] if duplicate else "已保存 " + record["path"]))
                                    success = True
                                    break
                                except (NeedsHuman, Stopped):
                                    raise
                                except (FileProblem, Error, TimeoutError, OSError, ValueError) as exc:
                                    reason = str(exc) if isinstance(exc, FileProblem) else "图片请求或本地写入异常"
                                    record["error"] = reason
                                    if attempt < 2:
                                        emit("图片失败：{}；重试 {}/2".format(reason, attempt + 1))
                                        if stop.wait(attempt + 1):
                                            raise Stopped()
                            if not success:
                                record["status"] = "failed"
                                failed += 1
                                result["image_failed"] += 1
                                emit("图片重试结束：{}".format(record["error"]))
                            manifest.save()
                            report()
                            if stop.wait(0.35):
                                raise Stopped()
                        lesson["status"] = "failed" if failed or lesson["warnings"] else "complete"
                        if lesson["warnings"]:
                            emit("未可靠提取：" + "；".join(lesson["warnings"]))
                        result["failed" if lesson["status"] == "failed" else "success"] += 1
                except NeedsHuman as exc:
                    lesson["status"] = "needs_human"
                    lesson["error"] = str(exc)
                    lesson["error_type"] = type(exc).__name__
                    manifest.save()
                    raise
                except Stopped:
                    lesson["status"] = "stopped"
                    manifest.save()
                    raise
                except (PageChanged, Error, FileProblem, KeyError, TypeError, ValueError) as exc:
                    if page.is_closed():
                        lesson["status"] = "stopped"
                        lesson["error"] = "浏览器已关闭，课时尚未完成"
                        lesson["error_type"] = type(exc).__name__
                        manifest.save()
                        raise NeedsHuman("浏览器已关闭，请重新启动下载") from None
                    lesson["status"] = "failed"
                    lesson["error"] = str(exc) if isinstance(exc, (PageChanged, FileProblem)) else "习题页面结构或资源提取异常"
                    lesson["error_type"] = type(exc).__name__
                    result["failed"] += 1
                    emit("本课时失败：{}；继续下一课时".format(lesson["error"]))
                result["completed"] += 1
                manifest.save()
                if on_lesson is not None:
                    on_lesson(task, dict(lesson))
                report()
                if stop.wait(0.8):
                    raise Stopped()
            result["status"] = "complete" if not result["failed"] else "partial"
        except Stopped:
            result["status"] = "stopped"
            emit("下载已停止，已完成文件保留，未完成资源下次重新处理")
        except NeedsHuman:
            result["status"] = "needs_human"
            raise
        finally:
            if on_lesson is not None:
                for task in tasks:
                    key = lesson_key(task)
                    if key in started_tasks:
                        on_lesson(task, dict(manifest.data["lessons"][key]))
            manifest.data["last_run"] = dict(result)
            manifest.save()
            report()
    return result
