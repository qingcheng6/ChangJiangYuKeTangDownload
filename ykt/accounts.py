"""Stable local accounts; legacy session is registered in place, never moved."""
import re
import shutil
import uuid
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit

from .files import safe_name
from .locking import LocalLock
from .storage import read_json, write_json


class Accounts:
    def __init__(self, root, origin):
        self.root = Path(root).resolve()
        self.origin = origin
        self.host = urlsplit(origin).hostname
        self.base = self.root / ".local" / "accounts" / self.host
        self.path = self.base / "registry.json"
        with LocalLock(self.base / ".registry.lock"):
            if not self.path.exists():
                legacy = self.root / ".local" / self.host
                owner = None
                try:
                    owner = read_json(legacy / "courses.json").get("owner_fingerprint")
                except (OSError, ValueError):
                    pass
                if not isinstance(owner, str) or not re.fullmatch(r"[0-9a-f]{64}", owner):
                    owner = None
                aid = uuid.uuid4().hex
                is_legacy = legacy.exists()
                name = "原有账号" if is_legacy else "默认账号"
                write_json(self.path, dict(schema_version=1, origin=origin, active_id=aid,
                    accounts=[dict(id=aid, name=name, legacy=is_legacy, owner=owner,
                        output_component=None if is_legacy else name + "_" + aid[:8], save_directory=None)]))
        self.reload()

    def reload(self):
        data = read_json(self.path)
        if data.get("origin") != self.origin or not isinstance(data.get("accounts"), list):
            raise ValueError("账号配置损坏，已保留原文件")
        seen = set()
        for row in data["accounts"]:
            if not isinstance(row, dict):
                raise ValueError("账号配置损坏，已保留原文件")
            aid = row.get("id")
            if (not isinstance(aid, str) or not re.fullmatch(r"[0-9a-f]{32}", aid) or aid in seen
                    or not isinstance(row.get("name"), str) or not row["name"].strip()
                    or type(row.get("legacy")) is not bool
                    or (row.get("owner") is not None and (not isinstance(row["owner"], str)
                        or not re.fullmatch(r"[0-9a-f]{64}", row["owner"])))):
                raise ValueError("账号配置损坏，已保留原文件")
            component = row.get("output_component")
            if not row["legacy"] and (not isinstance(component, str) or Path(component).name != component
                                      or component in (".", "..") or safe_name(component) != component):
                raise ValueError("账号输出目录配置无效")
            seen.add(aid)
        if sum(r["legacy"] for r in data["accounts"]) > 1 or data.get("active_id") not in seen | {None}:
            raise ValueError("账号配置损坏，已保留原文件")
        self.data = data
        return data

    @property
    def rows(self):
        return deepcopy(self.data["accounts"])

    def get(self, aid=None):
        aid = self.data["active_id"] if aid is None else aid
        return deepcopy(next((r for r in self.data["accounts"] if r["id"] == aid), None))

    def site_dir(self, row):
        target = (self.root / ".local" / self.host if row["legacy"] else self.base / row["id"])
        resolved = target.resolve()
        if resolved != target.absolute():
            raise ValueError("账号资料目录不能使用重定向链接")
        return resolved

    def update(self, aid, **values):
        if set(values) - {"name", "save_directory"}:
            raise ValueError("不允许更改账号归属或目录标识")
        with LocalLock(self.base / ".registry.lock"):
            self.reload()
            row = next((r for r in self.data["accounts"] if r["id"] == aid), None)
            if row is None:
                raise ValueError("账号已被删除")
            row.update(values)
            write_json(self.path, self.data)
        return self.get(aid)

    def activate(self, aid):
        with LocalLock(self.base / ".registry.lock"):
            self.reload()
            if not self.get(aid):
                raise ValueError("账号已被删除")
            self.data["active_id"] = aid
            write_json(self.path, self.data)

    def add(self, name):
        name = self.name(name)
        aid = uuid.uuid4().hex
        with LocalLock(self.base / ".registry.lock"):
            self.reload()
            self.data["accounts"].append(dict(id=aid, name=name, legacy=False, owner=None,
                output_component=safe_name(name, 35) + "_" + aid[:8], save_directory=None))
            write_json(self.path, self.data)
        return self.get(aid)

    @staticmethod
    def name(value):
        value = value.strip()
        if not value or len(value) > 60 or any(ord(c) < 32 for c in value):
            raise ValueError("账号名称应为1至60个可显示字符")
        return value

    def rename(self, aid, name):
        return self.update(aid, name=self.name(name))

    def bind(self, aid, owner):
        if not isinstance(owner, str) or not re.fullmatch(r"[0-9a-f]{64}", owner):
            raise ValueError("账号身份摘要无效")
        with LocalLock(self.base / ".registry.lock"):
            self.reload()
            row = next((r for r in self.data["accounts"] if r["id"] == aid), None)
            if row is None:
                raise ValueError("账号已被删除")
            if row.get("owner") not in (None, owner):
                raise ValueError("该账号资料中登录了其他账号，请切回原账号或新增独立账号")
            if row.get("owner") != owner:
                row["owner"] = owner
                write_json(self.path, self.data)

    def image_directory(self, row, selected):
        if row["legacy"]:
            return Path(selected)
        # V2 layout is selected explicitly; the legacy default remains unchanged.
        return Path(selected) / "雨课堂导出文件" / row["output_component"]

    def delete(self, aid):
        """Caller must confirm. Only fixed owned files; never follow links."""
        with LocalLock(self.base / ".registry.lock"):
            self.reload()
            row = self.get(aid)
            if row is None:
                raise ValueError("账号已被删除")
            site = self.site_dir(row)
            # Keep lease outside deletable files so Windows can remove browser.
            with LocalLock(site / ".exports.lock"), LocalLock(site / ".browser.lock"):
                targets = [site / n for n in ("browser", "courses.json", "exports.json")]
                for target in targets:
                    if target.exists() and (target.is_symlink() or target.resolve().parent != site
                            or getattr(target.lstat(), "st_file_attributes", 0) & 1024):
                        raise ValueError("账号资料路径异常，未删除")
                # Refuse junctions anywhere below the browser profile.
                browser = site / "browser"
                if browser.exists():
                    for item in browser.rglob("*"):
                        if item.is_symlink() or getattr(item.lstat(), "st_file_attributes", 0) & 1024:
                            raise ValueError("账号资料包含重定向路径，未删除")
                for target in targets:
                    if target.is_dir():
                        shutil.rmtree(target)
                    elif target.is_file():
                        target.unlink()
                self.data["accounts"] = [r for r in self.data["accounts"] if r["id"] != aid]
                if self.data["active_id"] == aid:
                    self.data["active_id"] = self.data["accounts"][0]["id"] if self.data["accounts"] else None
                write_json(self.path, self.data)
