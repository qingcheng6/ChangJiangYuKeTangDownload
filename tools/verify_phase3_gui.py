"""Visible, real-account GUI download verification; no simulated backend."""

import argparse
import sys
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ykt.gui import CourseApp
from ykt.storage import read_json, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stop-after-first", action="store_true")
    parser.add_argument("--auto", action="store_true")
    args = parser.parse_args()
    root = tk.Tk()
    app = CourseApp(root, ROOT)
    previous_directory = app.save_dir.get()
    directory = ROOT / ".local" / "phase3_gui_output"
    directory.mkdir(exist_ok=True)
    app.set_directory(str(directory))
    for name in ("工程经济学", "数学规划"):
        course = next(c for c in app.catalog["courses"] if c["name"] == name)
        app.toggle(app.lesson_iid((str(course["id"]), str(course["lessons"][0]["id"]))))
    ticks, running_ticks = 0, 0
    history = []
    last_state = None
    snapshot = {}
    stop_issued = False
    baseline = len(list(directory.rglob('*.jpg')))

    def observe():
        nonlocal ticks, running_ticks, last_state, snapshot, stop_issued
        ticks += 1
        running = app.worker.running
        running_ticks += running
        files = len(list(directory.rglob("*.jpg")))
        if args.stop_after_first and not stop_issued and running and files > baseline:
            stop_issued = True
            app.stop()
        state = (running, app.status.get())
        if state != last_state:
            history.append(dict(running=running, status=app.status.get(), files=files))
            last_state = state
        snapshot = dict(schema_version=1, ticks=ticks, running_ticks=running_ticks,
                        running=running, metrics={k: v.get() for k, v in app.metrics.items()},
                        selected=len(app.selection.selected), status=app.status.get(),
                        files=files, callback_errors=app.callback_errors,
                        ui_thread=app.ui_thread,
                        worker_thread=app.worker.thread.ident if app.worker.thread else None,
                        mode=app.worker.mode, stop_issued=stop_issued, history=history)
        manifests = list((directory / "雨课堂习题下载").glob("任务清单_*.json"))
        if manifests and not running:
            snapshot["last_run"] = read_json(manifests[0]).get("last_run")
        write_json(ROOT / ".local" / "phase3_gui_verification.json", snapshot)
        if stop_issued and not running and app.worker.stop_event.is_set():
            write_json(ROOT / ".local" / "phase3_gui_stop_verified.json", snapshot)
        root.after(250, observe)

    root.after(250, observe)
    if args.auto:
        root.after(1000, app.start_download)
    root.mainloop()
    snapshot.update(window_closed=True, worker_alive_after_close=app.worker.running)
    write_json(ROOT / ".local" / "phase3_gui_verification.json", snapshot)
    write_json(ROOT / ".local" / "gui_settings.json",
               dict(schema_version=1, save_directory=previous_directory))


if __name__ == "__main__":
    main()
