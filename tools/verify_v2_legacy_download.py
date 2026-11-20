"""Actual legacy profile + new worker ledger; old files are never written."""
import sys
import time
from pathlib import Path
from queue import Empty

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ykt.accounts import Accounts
from ykt.storage import read_json, write_json
from ykt.worker import ScanWorker


def run(accounts, row, tasks, directory):
    worker = ScanWorker(accounts.origin, accounts.site_dir(row), account_id=row["id"], expected_owner=row["owner"])
    worker.start_download(tasks, directory, row["owner"])
    events, result = [], None
    while worker.running or not worker.events.empty():
        try:
            kind, data = worker.events.get(timeout=0.25)
        except Empty:
            continue
        if kind == "log":
            print(data, flush=True)
        if kind == "download_result":
            result = data
        if kind in ("feature_progress", "resource_state", "error", "needs_human"):
            events.append(dict(kind=kind, data=data))
        if kind == "needs_human":
            worker.stop()
    worker.thread.join()
    assert result is not None and result["status"] == "complete", "Actual legacy download did not complete"
    return result, events


def main():
    accounts = Accounts(ROOT, "https://changjiang.yuketang.cn")
    row = next(r for r in accounts.rows if r["legacy"])
    cache_path = accounts.site_dir(row) / "courses.json"
    before = cache_path.read_bytes()
    cache = read_json(cache_path)
    historic = read_json(next((ROOT / ".local/phase3_output/雨课堂习题下载").glob("任务清单_*.json")))
    tasks = []
    for status in ("complete", "no_images"):
        record = next(l for l in historic["lessons"].values() if l["status"] == status)
        course = next(c for c in cache["courses"] if c["id"] == record["course_id"])
        lesson = next(l for l in course["lessons"] if l["id"] == record["lesson_id"])
        tasks.append(dict(course_id=course["id"], course_name=course["name"], class_name=course["class_name"], lesson=lesson))
    directory = ROOT / ".local/v2_stage1/legacy_output"
    directory.mkdir(exist_ok=True)
    first, events = run(accounts, row, tasks, directory)
    again, again_events = run(accounts, row, tasks, directory)
    assert first["success"] == 2 and first["no_images"] == 1
    assert again["downloaded"] == 0 and again["skipped"] == 14
    assert cache_path.read_bytes() == before
    write_json(ROOT / ".local/v2_stage1/legacy_download.json", dict(schema_version=1, first=first, restart=again,
        feature_events=events + again_events, legacy_cache_unchanged=True))
    print("LEGACY_WORKER_AND_FEATURE_STATE_VERIFIED", flush=True)


if __name__ == "__main__":
    main()
