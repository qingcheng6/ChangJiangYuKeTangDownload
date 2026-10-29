"""Windows-safe layout, image verification and atomic local task manifest."""

import hashlib
import io
import os
import re
import unicodedata
import warnings
from pathlib import Path

from PIL import Image, ImageFile, UnidentifiedImageError

from .storage import read_json, write_json

ImageFile.LOAD_TRUNCATED_IMAGES = False
EXTENSIONS = {"JPEG": ".jpg", "PNG": ".png", "GIF": ".gif", "WEBP": ".webp",
              "BMP": ".bmp", "TIFF": ".tif", "ICO": ".ico", "AVIF": ".avif"}


class FileProblem(Exception):
    pass


def units(value):
    return len(str(value).encode("utf-16-le")) // 2


def safe_name(value, budget=60):
    original = unicodedata.normalize("NFC", str(value))
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", original).strip().rstrip(". ")
    if not value:
        value = "未命名"
    stem = value.split(".", 1)[0].rstrip(" .").upper()
    if stem in {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} or re.fullmatch(r"(?:COM|LPT)[1-9¹²³]", stem):
        value = "_" + value
    if units(value) > budget:
        suffix = "_" + hashlib.sha256(original.encode()).hexdigest()[:min(8, max(1, budget - 1))]
        while value and units(value + suffix) > budget:
            value = value[:-1]
        value = value.rstrip(". ") + suffix
    return value


def image_info(data):
    if not data or len(data) > 64 * 1024 * 1024:
        raise FileProblem("图片为空或超过64MiB限制")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                fmt = image.format
                width, height = image.size
                if fmt not in EXTENSIONS or width < 1 or height < 1:
                    raise FileProblem("图片格式不受支持")
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                for index in range(getattr(image, "n_frames", 1)):
                    image.seek(index)
                    image.load()
        return dict(extension=EXTENSIONS[fmt], format=fmt, width=width, height=height,
                    size=len(data), sha256=hashlib.sha256(data).hexdigest())
    except (OSError, ValueError, SyntaxError, UnidentifiedImageError,
            Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise FileProblem("图片内容损坏、截断或无法可靠解码") from None


class Manifest:
    def __init__(self, directory, owner, origin):
        selected = Path(directory).resolve()
        self.root = (selected / "雨课堂习题下载").resolve()
        if self.root.parent != selected:
            raise FileProblem("下载目录指向外部位置，请选择其他保存目录")
        if not re.fullmatch(r"[0-9a-f]{64}", owner):
            raise FileProblem("账号标识无效，请重新扫描课程")
        self.owner = owner
        self.origin = origin
        # Leave room for two components, a collision suffix, filename and .part.
        self.budget = min(60, (235 - units(self.root) - 40) // 2)
        if self.budget < 14:
            raise FileProblem("保存目录路径过长，请选择较短的保存目录")
        self.path = self.root / ("任务清单_" + owner[:12] + ".json")
        self.lock = None
        self.data = None

    def __enter__(self):
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = (self.root / ".下载锁").open("a+b")
        if self.lock.tell() == 0:
            self.lock.write(b"0")
            self.lock.flush()
        self.lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lock.close()
            self.lock = None
            raise FileProblem("该保存目录已有下载任务，请等待任务结束") from None
        try:
            if self.path.exists():
                self.data = self.read_existing()
            else:
                self.data = dict(schema_version=1, owner=self.owner, origin=self.origin,
                                 courses={}, lessons={})
            return self
        except Exception:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *args):
        if self.lock is not None:
            self.lock.close()  # OS releases the advisory lock, also after a crash.
            self.lock = None

    def save(self):
        write_json(self.path, self.data)

    def read_existing(self):
        """Read-only validation; a damaged manifest is never silently replaced."""
        try:
            data = read_json(self.path)
            if (data.get("owner") != self.owner or data.get("origin") != self.origin or
                    not isinstance(data.get("lessons"), dict) or not isinstance(data.get("courses"), dict)):
                raise ValueError()
            for cid, component in data["courses"].items():
                if (not isinstance(cid, str) or not cid.isdigit() or not isinstance(component, str) or
                        len(Path(component).parts) != 1):
                    raise ValueError()
                self.resolve(component)
            for lesson in data["lessons"].values():
                if not isinstance(lesson, dict) or not isinstance(lesson.get("resources"), dict):
                    raise ValueError()
                for field in ("course_id", "lesson_id", "course_name", "lesson_name", "status"):
                    if not isinstance(lesson.get(field), str):
                        raise ValueError()
                if (not isinstance(lesson.get("warnings", []), list) or
                        any(not isinstance(reason, str) for reason in lesson.get("warnings", [])) or
                        ("error" in lesson and not isinstance(lesson["error"], str))):
                    raise ValueError()
                directory = self.resolve(lesson["directory"]) if lesson.get("directory") else None
                for record in lesson["resources"].values():
                    if not isinstance(record, dict) or record.get("status") not in (
                            "pending", "complete", "duplicate", "failed"):
                        raise ValueError()
                    if record.get("path") is not None:
                        path = self.resolve(record["path"])
                        if directory is None or directory not in path.parents:
                            raise ValueError()
                    if record["status"] in ("complete", "duplicate"):
                        if (not isinstance(record.get("sha256"), str) or
                                not re.fullmatch(r"[0-9a-f]{64}", record["sha256"]) or
                                type(record.get("size")) is not int or record["size"] <= 0 or
                                not record.get("path")):
                            raise ValueError()
            return data
        except FileNotFoundError:
            raise
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            raise FileProblem("任务清单无法读取或结构损坏；原清单未改动，请保留并检查或更换目录") from None

    def resolve(self, relative):
        if not isinstance(relative, str) or Path(relative).is_absolute():
            raise FileProblem("任务文件路径无效")
        path = (self.root / relative).resolve()
        if path == self.root or self.root not in path.parents:
            raise FileProblem("任务文件路径越出保存目录")
        if units(path) > 240:
            raise FileProblem("任务文件路径过长，请选择较短目录")
        return path

    def lesson(self, task):
        key = task["course_id"] + ":" + task["lesson"]["id"] + ":" + task["lesson"]["courseware_id"]
        return self.data["lessons"].setdefault(key, dict(
            course_id=task["course_id"], lesson_id=task["lesson"]["id"],
            course_name=task["course_name"], lesson_name=task["lesson"]["name"],
            status="pending", resources={}, directory=None))

    def _component(self, parent, label, identity, used):
        value = safe_name(label, self.budget)
        reserved = {name.casefold() for name in used}
        if value.casefold() in reserved or (parent / value).exists():
            suffix = "_" + hashlib.sha256(identity.encode()).hexdigest()[:8]
            value = safe_name(label, self.budget - len(suffix)) + suffix
        counter = 1
        initial = value
        while value.casefold() in reserved or (parent / value).exists():
            suffix = "_" + str(counter)
            value = safe_name(initial, self.budget - len(suffix)) + suffix
            counter += 1
        return value

    def directory_for(self, task, lesson):
        if lesson["directory"]:
            return self.resolve(lesson["directory"])
        cid = task["course_id"]
        courses = self.data["courses"]
        if cid not in courses:
            courses[cid] = self._component(self.root, task["course_name"], cid, courses.values())
        parent = self.resolve(courses[cid])
        used = [Path(item["directory"]).name for item in self.data["lessons"].values()
                if item.get("directory") and str(Path(item["directory"]).parent) == courses[cid]]
        name = self._component(parent, task["lesson"]["name"], task["lesson"]["id"], used)
        lesson["directory"] = str(Path(courses[cid]) / name)
        return self.resolve(lesson["directory"])

    def verified(self, record):
        if record.get("status") not in ("complete", "duplicate"):
            return False
        try:
            path = self.resolve(record["path"])
            if not path.is_file() or path.stat().st_size != record["size"]:
                return False
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            return digest.hexdigest() == record["sha256"]
        except (FileProblem, OSError, KeyError, TypeError):
            return False

    def output_path(self, task, lesson, record, info, order, resource_id):
        parent = self.directory_for(task, lesson)
        existing = record.get("path")
        if existing and self.resolve(existing).suffix.lower() == info["extension"]:
            return self.resolve(existing)
        base = "习题_{:03d}".format(order)
        path = parent / (base + info["extension"])
        other_paths = {r.get("path") for r in lesson["resources"].values() if r is not record}
        count = 0
        while path.exists() or str(path.relative_to(self.root)) in other_paths:
            count += 1
            path = parent / (base + "_" + resource_id[:8] +
                             ("_" + str(count) if count > 1 else "") + info["extension"])
        self.resolve(str(path.relative_to(self.root)))
        return path
