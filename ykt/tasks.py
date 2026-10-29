"""Account-scoped feature status; courseware PDF remains unimplemented."""
import hashlib
from datetime import datetime, timezone

from .locking import LocalLock
from .storage import read_json, write_json

FEATURES = ("quiz_images", "quiz_pdf", "courseware_pdf")
RESOURCE_LABELS = {"available": "有资源", "absent": "无资源", "unknown": "未知", "error": "检查失败"}


def validate(data, account_id, origin):
    if (data.get("account_id") != account_id or data.get("origin") != origin
            or not isinstance(data.get("tasks"), dict)):
        raise ValueError("导出状态文件不匹配，原文件已保留")
    for key, row in data["tasks"].items():
        if (not isinstance(key, str) or not isinstance(row, dict) or row.get("account_id") != account_id
                or row.get("feature") not in FEATURES or row.get("resource_state") not in RESOURCE_LABELS
                or any(not isinstance(row.get(f), str) for f in ("course_id", "lesson_id", "courseware_id", "status"))):
            raise ValueError("导出状态结构异常，原文件已保留")


def task_key(account_id, task, feature):
    parts = [account_id, task["course_id"], task["lesson"]["id"], task["lesson"]["courseware_id"], feature]
    return hashlib.sha256(":".join(parts).encode()).hexdigest()


class TaskLedger:
    def __init__(self, site_dir, account_id, origin):
        self.path = site_dir / "exports.json"
        self.account_id = account_id
        self.origin = origin
        self.lock = LocalLock(site_dir / ".exports.lock")

    def __enter__(self):
        self.lock.__enter__()
        try:
            if self.path.exists():
                self.data = read_json(self.path)
                validate(self.data, self.account_id, self.origin)
            else:
                self.data = dict(schema_version=1, account_id=self.account_id, origin=self.origin, tasks={})
            return self
        except Exception:
            self.lock.__exit__(None, None, None)
            raise

    def __exit__(self, *args):
        self.lock.__exit__(*args)

    def begin(self, tasks, options):
        self.keys = []
        for task in tasks:
            for feature in FEATURES:
                key = task_key(self.account_id, task, feature)
                selected = bool(options.get(feature))
                if not selected and key in self.data["tasks"]:
                    continue
                self.data["tasks"][key] = dict(account_id=self.account_id, course_id=task["course_id"],
                    lesson_id=task["lesson"]["id"], courseware_id=task["lesson"]["courseware_id"],
                    course_name=task["course_name"], lesson_name=task["lesson"]["name"], feature=feature,
                    status=("pending" if feature in ("quiz_images", "quiz_pdf") else "not_implemented") if selected else "not_selected",
                    resource_state="unknown", error=None, error_type=None)
                if selected:
                    self.keys.append(key)
        self.save()

    def lesson(self, task, lesson):
        record = self.data["tasks"][task_key(self.account_id, task, "quiz_images")]
        record["status"] = lesson["status"]
        record["error"] = lesson.get("error")
        record["error_type"] = lesson.get("error_type")
        record["resource_state"] = ("absent" if lesson["status"] == "no_images" else
            "available" if lesson.get("quiz_pages", 0) > 0 else
            "error" if lesson["status"] == "failed" else "unknown")
        self.save()
        return dict(record)

    def feature(self, task, feature, result):
        record = self.data["tasks"][task_key(self.account_id, task, feature)]
        for field in ("status", "resource_state", "error", "error_type", "path", "sha256", "size", "pages", "skipped"):
            if field in result:
                record[field] = result[field]
        self.save()
        return dict(record)

    def interrupt(self, status, reason=None):
        for key in self.keys:
            record = self.data["tasks"][key]
            if record["status"] in ("pending", "running"):
                record.update(status=status, error=reason)
        self.save()

    def save(self):
        self.data["updated_at"] = datetime.now(timezone.utc).isoformat()
        write_json(self.path, self.data)

    def counts(self):
        results = {f: dict(total=0, success=0, failed=0, completed=0) for f in FEATURES}
        for key in self.keys:
            r = self.data["tasks"][key]
            c = results[r["feature"]]
            c["total"] += 1
            if r["status"] in ("complete", "no_images"):
                c["success"] += 1
                c["completed"] += 1
            elif r["status"] in ("failed", "not_implemented"):
                c["failed"] += 1
                c["completed"] += 1
        return results


def resource_states(site_dir, account_id, origin):
    path = site_dir / "exports.json"
    if not path.exists():
        return {}
    data = read_json(path)
    validate(data, account_id, origin)
    results = {}
    for row in data["tasks"].values():
        results[(row["course_id"], row["lesson_id"], row["feature"])] = row.get("resource_state", "unknown")
    return results
