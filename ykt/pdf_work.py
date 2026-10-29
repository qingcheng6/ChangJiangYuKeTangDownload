"""Persistent temporary images for PDF-only resume; no historical deletion."""
import hashlib
import shutil
import tempfile
from copy import deepcopy
from pathlib import Path

from .files import Manifest, FileProblem, image_info
from .locking import LocalLock
from .storage import read_json, write_json
from .browser import check_stop


class PdfWork:
    def __init__(self, site_dir, account_id, task, owner, origin):
        identity = str(site_dir.resolve()) + ":" + account_id + ":" + task["course_id"] + ":" + task["lesson"]["id"] + ":" + task["lesson"]["courseware_id"]
        self.key = hashlib.sha256(identity.encode()).hexdigest()
        self.base = (Path(tempfile.gettempdir()) / "ykt_pdf_work").resolve()
        self.root = self.base / self.key
        self.marker = dict(schema_version=1, purpose="quiz_pdf_temporary_images", key=self.key)
        self.lease = LocalLock(self.base / (self.key + ".lock"))
        self.owner, self.origin, self.task = owner, origin, task
        self.discard = False

    def __enter__(self):
        self.lease.__enter__()
        try:
            if self.root.resolve() != self.root or self.root.parent != self.base:
                raise FileProblem("PDF临时目录归属异常")
            self.root.mkdir(parents=True, exist_ok=True)
            marker = self.root / "ownership.json"
            if marker.exists():
                if read_json(marker) != self.marker:
                    raise FileProblem("PDF临时目录标识不匹配，未改动")
            elif any(self.root.iterdir()):
                raise FileProblem("PDF临时目录已有未知内容，未改动")
            else:
                write_json(marker, self.marker)
            return self
        except Exception:
            self.lease.__exit__(None, None, None)
            raise

    def seed(self, source, stop=None):
        target = Manifest(self.root, self.owner, self.origin)
        if target.path.exists() or not source.path.exists():
            return
        data = source.read_existing()
        key = self.task["course_id"] + ":" + self.task["lesson"]["id"] + ":" + self.task["lesson"]["courseware_id"]
        old = data["lessons"].get(key)
        if not old:
            return
        with target as cache:
            lesson = cache.lesson(self.task)
            for index, (rid, rec) in enumerate(old["resources"].items(), 1):
                if stop is not None:
                    check_stop(stop)
                if not source.verified(rec):
                    continue
                image = source.resolve(rec["path"]).read_bytes()
                info = image_info(image)
                if info["sha256"] != rec["sha256"]:
                    continue
                parent = cache.directory_for(self.task, lesson)
                path = parent / ("seed_{:04d}".format(index) + info["extension"])
                cache.resolve(str(path.relative_to(cache.root)))
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(image)
                record = deepcopy(rec)
                record.update(status="complete", path=str(path.relative_to(cache.root)))
                record.pop("duplicate_of", None)
                lesson["resources"][rid] = record
            cache.save()

    def __exit__(self, *args):
        try:
            if self.discard:
                if (self.root.resolve() != self.root or self.root.parent != self.base
                        or read_json(self.root / "ownership.json") != self.marker):
                    raise FileProblem("PDF临时目录清理校验失败，未删除")
                for item in self.root.rglob("*"):
                    if item.is_symlink() or getattr(item.lstat(), "st_file_attributes", 0) & 1024:
                        raise FileProblem("PDF临时目录含重定向路径，未删除")
                # Only this fixed SHA-256 child with our ownership marker;
                # source/user directories are never accepted as cleanup targets.
                shutil.rmtree(self.root)
        finally:
            self.lease.__exit__(*args)
