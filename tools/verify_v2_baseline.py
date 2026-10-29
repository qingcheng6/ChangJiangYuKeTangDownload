"""Stage 0 only: real V1 scan/download checks in a separate local output.

Does not change selectors, business behavior, configuration or historic tasks.
"""
import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path
from threading import Event

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ykt.browser import NeedsHuman, ensure_login, open_browser
from ykt.downloader import download
from ykt.files import Manifest
from ykt.scanner import archived_catalog, course_catalog, scan_lessons
from ykt.storage import read_json, write_json


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    location = read_json(ROOT / ".local/v2_stage0_location.json")
    target = Path(location["directory"]).resolve()
    assert (ROOT / ".local/v2_stage0").resolve() in target.parents
    proof = dict(schema_version=1, status="running", simulated_website_data=False)
    cache_path = ROOT / ".local/changjiang.yuketang.cn/courses.json"
    cache = read_json(cache_path)
    protected = [cache_path, ROOT / ".local/gui_settings.json"]
    for path in (ROOT / ".local").rglob("*"):
        if not path.is_file():
            continue
        parts = path.relative_to(ROOT / ".local").parts
        if any(part in ("v2_stage0", "browser", ".venv") or part.startswith("release_smoke_") for part in parts):
            continue
        if path.name.startswith("任务清单_") or path.suffix.lower() in (".jpg", ".png", ".pdf"):
            protected.append(path)
    protected = list(dict.fromkeys(p for p in protected if p.exists()))
    before = {p: digest(p) for p in protected}
    course = deepcopy(next(c for c in cache["courses"] if c["name"] == "工程经济学"))
    no_quiz = next(c for c in cache["courses"] if c["name"] == "数学规划")
    historical_manifest = read_json(next((ROOT / ".local/phase3_output/雨课堂习题下载").glob("任务清单_*.json")))
    verified_empty_ids = {l["lesson_id"] for l in historical_manifest["lessons"].values()
                          if l["status"] == "no_images"}
    empty = next(l for l in no_quiz["lessons"] if l["id"] in verified_empty_ids)
    output = target / "probe_output"
    output.mkdir(exist_ok=True)
    stop = Event()
    def emit(message):
        print(message, flush=True)
    try:
        with open_browser(ROOT / ".local/changjiang.yuketang.cn/browser", emit) as (context, page):
            ensure_login(page, cache["origin"], stop, emit, timeout_ms=15000)
            catalog = course_catalog(page, stop)
            owner = hashlib.sha256((cache["origin"] + ":" + catalog["account"]).encode()).hexdigest()
            assert owner == cache["owner_fingerprint"], "Current owner differs from cached baseline"
            archives = archived_catalog(page, stop)
            proof["live_catalog"] = dict(regular=len(catalog["courses"]), archived=len(archives))
            scan_lessons(page, course, cache["origin"], stop, emit)
            proof["live_course_scan"] = dict(lessons=len(course["lessons"]), pagination=course["pagination"])
            quiz = next(l for l in course["lessons"] if l.get("is_finished") is not False)
            tasks = [dict(course_id=c["id"], course_name=c["name"], class_name=c["class_name"], lesson=deepcopy(l))
                     for c,l in ((course,quiz),(no_quiz,empty))]
            first = download(context, page, cache["origin"], tasks, output, owner, stop, emit)
            assert first["status"] == "complete" and first["success"] == 2 and first["downloaded"] > 0
            assert first["no_images"] == 1
        # A new context verifies persistent login and resume across a restart.
        files = {p: (digest(p), p.stat().st_mtime_ns) for p in output.rglob("*.jpg")}
        with open_browser(ROOT / ".local/changjiang.yuketang.cn/browser", emit) as (context, page):
            again = download(context, page, cache["origin"], tasks, output, owner, stop, emit)
        assert again["status"] == "complete" and again["downloaded"] == 0
        assert again["skipped"] == first["downloaded"]
        assert all((digest(p),p.stat().st_mtime_ns)==v for p,v in files.items())
        m = Manifest(output, owner, cache["origin"])
        data = m.read_existing()
        assert all(m.verified(r) for l in data["lessons"].values() for r in l["resources"].values())
        assert all(not l["directory"] for l in data["lessons"].values() if l["status"]=="no_images")
        proof.update(status="passed", first_download=first, restart=again,
                     verified_output_files=len(files), output_mtime_preserved=True)
    except NeedsHuman as exc:
        proof.update(status="needs_human", reason=str(exc))
    finally:
        unchanged = all(p.is_file() and digest(p)==sha for p,sha in before.items())
        proof.update(protected_historical_files=len(before), historical_content_unchanged=unchanged)
        write_json(target / "live_baseline.json", proof)
        assert unchanged, "Historical file changed during baseline"
    print("BASELINE_STATUS="+proof["status"], flush=True)
    return 0 if proof["status"] == "passed" else 3


if __name__ == "__main__":
    sys.exit(main())
