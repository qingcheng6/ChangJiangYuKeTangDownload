"""Real catalog completion flag; do not enter the live classroom."""
import sys
from pathlib import Path
from threading import Event

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ykt.browser import open_browser
from ykt.downloader import download
from ykt.storage import read_json, write_json


def main():
    cache = read_json(ROOT / ".local/changjiang.yuketang.cn/courses.json")
    course = next(c for c in cache["courses"] if any(l.get("is_finished") is False for l in c["lessons"]))
    lesson = next(l for l in course["lessons"] if l.get("is_finished") is False)
    task = dict(course_id=course["id"], course_name=course["name"], class_name=course["class_name"], lesson=lesson)
    directory = ROOT / ".local/phase4_ongoing"
    directory.mkdir(exist_ok=True)
    with open_browser(ROOT / ".local/changjiang.yuketang.cn/browser", print, channel="chrome") as (context, page):
        reports = []
        page.on("request", lambda r: reports.append(True) if "student-lesson-report" in r.url else None)
        result = download(context, page, cache["origin"], [task], directory,
                          cache["owner_fingerprint"], Event(), print)
    manifest = read_json(next((directory / "雨课堂习题下载").glob("任务清单_*.json")))
    record = next(iter(manifest["lessons"].values()))
    assert result["failed"] == 1 and result["downloaded"] == 0 and not reports
    assert "尚未结束" in record["error"]
    write_json(ROOT / ".local/phase4_ongoing_verified.json",
               dict(result=result, reason=record["error"], report_request_count=len(reports)))


if __name__ == "__main__":
    main()
