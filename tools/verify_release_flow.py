"""Real GUI scan -> choose mixed lessons -> download; no substitute data."""

import sys
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ykt.gui import CourseApp
from ykt.storage import read_json, write_json


def main():
    root = tk.Tk()
    app = CourseApp(root, ROOT)
    previous_directory = app.save_dir.get()
    directory = ROOT / ".local" / "phase4_e2e"
    directory.mkdir(exist_ok=True)
    app.set_directory(str(directory))
    stage, ticks, running_ticks = "starting", 0, 0
    scan_started = False
    proof = dict(schema_version=1, stages=[], callback_errors=[])

    def start():
        nonlocal stage, scan_started
        stage = "scanning"
        app.start_scan()
        scan_started = True

    def observe():
        nonlocal stage, ticks, running_ticks
        ticks += 1
        running_ticks += app.worker.running
        if stage == "scanning" and scan_started and not app.worker.running:
            if app.catalog and app.catalog["status"] == "complete" and app.metrics["failed"].get() == 0:
                proof["scan"] = dict(courses=len(app.catalog["courses"]),
                                     lessons=sum(len(c["lessons"]) for c in app.catalog["courses"]))
                proof["stages"].append("real_scan_complete")
                app.clear_selection()
                for name, count in (("工程经济学", 2), ("数学规划", 1),
                                     ("马克思主义基本原理", 1), ("高等数学A1", 2), ("普通化学B", 1)):
                    course = next(c for c in app.catalog["courses"] if c["name"] == name and c["lessons"])
                    for lesson in [l for l in course["lessons"] if l.get("is_finished") is not False][:count]:
                        app.toggle(app.lesson_iid((str(course["id"]), str(lesson["id"]))))
                proof["selected_tasks"] = len(app.selection.selected)
                stage = "downloading"
                app.start_download()
            else:
                stage = "scan_failed"
        if stage == "downloading" and not app.worker.running:
            stage = "finished"
            manifests = list((directory / "雨课堂习题下载").glob("任务清单_*.json"))
            if manifests:
                data = read_json(manifests[0])
                proof["download"] = data.get("last_run")
                proof["unfinished"] = [dict(name=l["lesson_name"], status=l["status"],
                                             error=l.get("error"), warnings=l.get("warnings"))
                                       for l in data["lessons"].values()
                                       if l["status"] not in ("complete", "no_images")]
            proof["stages"].append("real_download_finished")
        proof.update(stage=stage, ticks=ticks, running_ticks=running_ticks,
                     running=app.worker.running, waiting_human=app.waiting_human,
                     metrics={k: v.get() for k, v in app.metrics.items()},
                     status=app.status.get(), callback_errors=app.callback_errors,
                     ui_thread=app.ui_thread,
                     worker_thread=app.worker.thread.ident if app.worker.thread else None)
        write_json(ROOT / ".local" / "phase4_e2e_verification.json", proof)
        root.after(250, observe)

    root.after(500, start)
    root.after(250, observe)
    root.mainloop()
    proof.update(window_closed=True, worker_alive_after_close=app.worker.running)
    write_json(ROOT / ".local" / "phase4_e2e_verification.json", proof)
    write_json(ROOT / ".local" / "gui_settings.json",
               dict(schema_version=1, save_directory=previous_directory))


if __name__ == "__main__":
    main()
