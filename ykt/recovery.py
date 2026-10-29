"""Read persisted unfinished tasks; never treats this view as file verification."""

from .files import Manifest


def unfinished(directory, owner, origin, layout="legacy"):
    manifest = Manifest(directory, owner, origin, layout=layout)
    data = manifest.read_existing()
    results = []
    for lesson in data["lessons"].values():
        reasons = []
        for record in lesson["resources"].values():
            if record.get("status") in ("failed", "pending"):
                reasons.append(record.get("error") or "图片尚未完成")
        reasons.extend(lesson.get("warnings", []))
        if lesson.get("error"):
            reasons.append(lesson["error"])
        if lesson["status"] not in ("complete", "no_images") or reasons:
            results.append(dict(course_id=lesson["course_id"], lesson_id=lesson["lesson_id"],
                                course_name=lesson["course_name"], lesson_name=lesson["lesson_name"],
                                status=lesson["status"], reasons=list(dict.fromkeys(reasons))))
    return results
