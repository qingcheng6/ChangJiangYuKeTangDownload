"""Explicit real-account download probe. Never supplies simulated resources.

Default: one real quiz lesson plus a verified no-quiz lesson from the local
course cache. --stop requests a safe stop after the first image is saved.
"""

import argparse
import sys
from pathlib import Path
from threading import Event

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ykt.browser import open_browser
from ykt.downloader import download
from ykt.storage import read_json, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, default=ROOT / ".local" / "phase3_output")
    parser.add_argument("--stop", action="store_true")
    args = parser.parse_args()
    cache = read_json(ROOT / ".local" / "changjiang.yuketang.cn" / "courses.json")
    courses = [next(c for c in cache["courses"] if c["name"] == name)
               for name in ("工程经济学", "数学规划")]
    tasks = [dict(course_id=c["id"], course_name=c["name"], class_name=c["class_name"],
                  lesson=dict(c["lessons"][0])) for c in courses]
    args.directory.mkdir(parents=True, exist_ok=True)
    stop = Event()
    def emit(message):
        print(message, flush=True)
        if args.stop and "：已保存 " in message:
            stop.set()
    with open_browser(ROOT / ".local" / "changjiang.yuketang.cn" / "browser", emit,
                      channel="chrome") as (context, page):
        result = download(context, page, cache["origin"], tasks, args.directory,
                          cache["owner_fingerprint"], stop, emit)
    print("RESULT", result, flush=True)
    write_json(ROOT / ".local" / "phase3_last_probe.json", dict(schema_version=1, result=result,
               directory=str(args.directory.resolve())))
    return 0 if result["status"] in ("complete", "stopped") else 2


if __name__ == "__main__":
    sys.exit(main())
