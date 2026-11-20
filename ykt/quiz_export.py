"""Optional quiz PDF orchestration, using the single existing image downloader."""
from contextlib import nullcontext

from .browser import Stopped, check_stop
from .downloader import download, verify_account
from .files import Manifest
from .pdf_work import PdfWork
from .quiz_pdf import merge_lesson, verified_pdf
from .naming import lesson_key
from .quiz_grid import courseware_field, field_for, layout_suffix, normalize_layout


def _record_pending_pdfs(request, origin, layout, features):
    """Persist selected intent before images run; never reset completed output."""
    with Manifest(request["directory"], request["owner"], origin, layout=layout) as formal:
        changed = False
        for task in request["tasks"]:
            key = lesson_key(task)
            new = key not in formal.data["lessons"]
            count = len(formal.data['lessons'])
            lesson = formal.lesson(task)
            changed |= len(formal.data['lessons']) != count
            if new and request.get('naming'):
                task.setdefault('_naming_created_pending', []).append(key)
            if new and not request["options"].get("quiz_images"):
                lesson["status"] = "pdf_only"
            changed |= new
            for feature in features:
                field = (field_for(request['options']) if feature == 'quiz_pdf'
                         else courseware_field(request['options'].get('quiz_layout')))
                if field not in lesson:
                    lesson[field] = dict(status="pending", error=None, error_type=None)
                    changed = True
        if changed:
            formal.save()
        if request.get('naming'):
            request['naming'].registered = True


def export_quizzes(context, page, origin, request, site_dir, account_id, layout, stop,
                   emit, image_done, feature_done, progress):
    keep_images = request["options"]["quiz_images"]
    answers = bool(request['options'].get('quiz_answers'))
    spec = normalize_layout(request['options'].get('quiz_layout'))
    field = field_for(request['options'])
    result = dict(total=len(request["tasks"]), completed=0, success=0, failed=0,
        status="running", downloaded=0, skipped=0, image_failed=0, no_images=0,
        current_course="—", current_lesson="—")
    verify_account(page, origin, request["owner"], stop, emit)
    _record_pending_pdfs(request, origin, layout, ("quiz_pdf",))
    layout_label = layout_suffix(spec).lstrip('_') if spec is not None else '单题一页'
    try:
        for task in request["tasks"]:
            check_stop(stop)
            if request.get('naming'):
                request['naming'].bind(task, emit)
            result.update(current_course=task["course_name"], current_lesson=task["lesson"]["name"])
            progress(dict(result))
            prefix = "[习题PDF] {} / {}：".format(" ".join(task["course_name"].split()), " ".join(task["lesson"]["name"].split()))
            target = Manifest(request["directory"], request["owner"], origin, layout=layout)
            key = lesson_key(task)
            # Valid tracked PDF-only results need no temporary images or image
            # requests. Ownership was verified above; existence alone is never enough.
            if not keep_images and target.path.exists():
                with target as formal:
                    old = formal.data["lessons"].get(key, {}).get(field, {})
                    if verified_pdf(formal, old, stop, answers=answers,grid=spec):
                        feature_done(task, "quiz_pdf", dict(old, resource_state="available", skipped=True))
                        emit(prefix + "已校验同排版合集，{}，{}题/{}页，跳过：{}".format(
                            layout_label, old.get('question_count', old['pages']), old['pages'],
                            formal.resolve(old['path'])))
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
                    layout=source_layout, naming=request.get('naming'), answers=answers)
                for metric in ("downloaded", "skipped", "image_failed", "no_images"):
                    result[metric] += images[metric]
                if images["status"] == "stopped":
                    raise Stopped()
                source = Manifest(source_directory, request["owner"], origin, layout=source_layout)
                source_lesson = source.read_existing()["lessons"][key]
                with target as formal:
                    pdf = merge_lesson(formal, task, source, source_lesson, stop,
                                       lambda message: emit(prefix + message), answers=answers,grid=spec)
                feature_done(task, "quiz_pdf", pdf)
                if pdf['status'] == 'no_images':
                    emit(prefix + '没有可导出的习题图片，本次未生成{}合集。历史合集仍可在原目录查看。'.format(layout_label))
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
