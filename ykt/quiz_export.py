"""Optional quiz PDF orchestration, using the single existing image downloader."""
from contextlib import nullcontext

from .browser import Stopped, check_stop
from .downloader import download, verify_account
from .files import Manifest
from .pdf_work import PdfWork
from .quiz_pdf import merge_lesson, verified_pdf


def export_quizzes(context, page, origin, request, site_dir, account_id, layout, stop,
                   emit, image_done, feature_done, progress):
    keep_images = request["options"]["quiz_images"]
    result = dict(total=len(request["tasks"]), completed=0, success=0, failed=0,
        status="running", downloaded=0, skipped=0, image_failed=0, no_images=0,
        current_course="—", current_lesson="—")
    verify_account(page, origin, request["owner"], stop, emit)
    try:
        for task in request["tasks"]:
            check_stop(stop)
            result.update(current_course=task["course_name"], current_lesson=task["lesson"]["name"])
            progress(dict(result))
            prefix = "[习题PDF] {} / {}：".format(" ".join(task["course_name"].split()), " ".join(task["lesson"]["name"].split()))
            target = Manifest(request["directory"], request["owner"], origin, layout=layout)
            key = task["course_id"] + ":" + task["lesson"]["id"] + ":" + task["lesson"]["courseware_id"]
            # Valid tracked PDF-only results need no temporary images or image
            # requests. Ownership was verified above; existence alone is never enough.
            if not keep_images and target.path.exists():
                with target as formal:
                    old = formal.data["lessons"].get(key, {}).get("quiz_pdf", {})
                    if verified_pdf(formal, old, stop):
                        feature_done(task, "quiz_pdf", dict(old, resource_state="available", skipped=True))
                        emit(prefix + "PDF完整且任务已完成，跳过；未创建临时图片")
                        result["completed"] += 1
                        result["success"] += 1
                        progress(dict(result))
                        continue
            workspace = (nullcontext(None) if keep_images else
                PdfWork(site_dir, account_id, task, request["owner"], origin))
            with workspace as work:
                if work:
                    work.seed(target, stop)
                source_directory = work.root if work else request["directory"]
                source_layout = "legacy" if work else layout
                def transfer_update(update):
                    current = dict(result)
                    for metric in ("downloaded", "skipped", "image_failed"):
                        current[metric] += update[metric]
                    progress(current)
                images = download(context, page, origin, [task], source_directory, request["owner"],
                    stop, lambda message: emit(("[临时习题图片] " if work else "[习题图片] ") + message),
                    on_progress=transfer_update, on_lesson=image_done if keep_images else None,
                    layout=source_layout)
                for metric in ("downloaded", "skipped", "image_failed", "no_images"):
                    result[metric] += images[metric]
                if images["status"] == "stopped":
                    raise Stopped()
                source = Manifest(source_directory, request["owner"], origin, layout=source_layout)
                source_lesson = source.read_existing()["lessons"][key]
                with target as formal:
                    pdf = merge_lesson(formal, task, source, source_lesson, stop,
                                       lambda message: emit(prefix + message))
                feature_done(task, "quiz_pdf", pdf)
                if work and pdf["status"] in ("complete", "no_images"):
                    work.discard = True
                result["completed"] += 1
                successful = pdf["status"] in ("complete", "no_images") and (not keep_images or images["failed"] == 0)
                result["success" if successful else "failed"] += 1
                progress(dict(result))
        result["status"] = "partial" if result["failed"] else "complete"
    except Stopped:
        result["status"] = "stopped"
        emit("导出已停止，完整图片/PDF保留；PDF临时缓存留待恢复")
    progress(dict(result))
    return result
