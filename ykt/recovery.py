"""Read persisted unfinished tasks; never treats this view as file verification."""

from .files import Manifest


def unfinished(directory, owner, origin, layout="legacy", features=None):
    manifest = Manifest(directory, owner, origin, layout=layout)
    data = manifest.read_existing()
    results = []
    features = {"quiz_images"} if features is None else set(features)
    for lesson in data["lessons"].values():
        reasons = []
        image_unfinished = False
        if "quiz_images" in features and lesson["status"] != "pdf_only":
            for record in lesson["resources"].values():
                if record.get("status") in ("failed", "pending"):
                    reasons.append(record.get("error") or "图片尚未完成")
            reasons.extend(lesson.get("warnings", []))
            if lesson.get("error"):
                reasons.append(lesson["error"])
            image_unfinished = lesson["status"] not in ("complete", "no_images")
        pdf = lesson.get("quiz_pdf")
        if pdf is not None and not isinstance(pdf, dict):
            raise ValueError("PDF任务记录异常")
        pdf_unfinished = "quiz_pdf" in features and pdf and pdf.get("status") not in ("complete", "no_images")
        if pdf_unfinished:
            reasons.append("[习题PDF] " + (pdf.get("error") or "PDF尚未完成"))
        if image_unfinished or pdf_unfinished or reasons:
            results.append(dict(course_id=lesson["course_id"], lesson_id=lesson["lesson_id"],
                                course_name=lesson["course_name"], lesson_name=lesson["lesson_name"],
                                status=pdf.get("status") if pdf_unfinished else lesson["status"],
                                reasons=list(dict.fromkeys(reasons))))
    return results
