"""Controlled failure: close the actual authorized browser after report loading.

No HTTP/DOM success is fabricated. The expected outcome is an unfinished task.
"""

import sys
from pathlib import Path
from threading import Event

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ykt.browser import NeedsHuman, open_browser
from ykt.downloader import download
from ykt.storage import read_json, write_json


def main():
    cache = read_json(ROOT / ".local" / "changjiang.yuketang.cn" / "courses.json")
    course = next(c for c in cache["courses"] if c["name"] == "工程经济学")
    task = dict(course_id=course["id"], course_name=course["name"], class_name=course["class_name"],
                lesson=dict(course["lessons"][0]))
    directory = ROOT / ".local" / "phase4_browser_closed"
    directory.mkdir(exist_ok=True)
    closed = False
    outcome = None
    with open_browser(ROOT / ".local" / "changjiang.yuketang.cn" / "browser", print,
                      channel="chrome") as (context, page):
        def emit(message):
            nonlocal closed
            print(message, flush=True)
            # This is the application caller, not a reentrant transport-event
            # callback. The normal authorized report has already been verified.
            if not closed and message.startswith("已核对 "):
                closed = True
                context.close()
        try:
            download(context, page, cache["origin"], [task], directory,
                     cache["owner_fingerprint"], Event(), emit)
        except NeedsHuman:
            outcome = "needs_human"
    assert closed and outcome == "needs_human"
    data = read_json(next((directory / "雨课堂习题下载").glob("任务清单_*.json")))
    lesson = next(iter(data["lessons"].values()))
    assert lesson["status"] == "stopped" and "浏览器已关闭" in lesson["error"]
    assert data["last_run"]["status"] == "needs_human"
    proof = dict(schema_version=1, actual_browser_closed=True, outcome=outcome,
                 completed=data["last_run"]["completed"], failed_reason=lesson["error"],
                 no_image_file_created=not list(directory.rglob("*.jpg")))
    write_json(ROOT / ".local" / "phase4_browser_close_verified.json", proof)
    print("ACTUAL_BROWSER_CLOSE_LEFT_AN_UNFINISHED_TASK", flush=True)


if __name__ == "__main__":
    main()
