"""Stage 1 observer for existing authorized profiles; never fabricates data."""
import sys
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ykt.gui import CourseApp
from ykt.storage import read_json, write_json


def main():
    directory = ROOT / ".local/v2_stage1"
    prior = read_json(directory / "gui_live.json")
    root = tk.Tk()
    app = CourseApp(root, ROOT, account_id=prior["new_account_id"])
    root.title("雨课堂习题图片下载工具 — 阶段1验收")
    proof = dict(schema_version=1, ticks=0, commands=[], downloads=[], switches=[], callback_errors=[], observer_io_errors=[])
    last_worker = app.worker
    stop_scan_for = None
    switch_after_image = None
    command_file = directory / "acceptance_command.json"
    if command_file.exists():
        command_file.unlink()  # This observer's exact command file only.
    original_handler = app._handle_event

    def handle(kind, data):
        original_handler(kind, data)
        if kind == "download_result":
            proof["downloads"].append(dict(data))
        if kind == "result":
            proof["scan"] = dict(status=data["status"], courses=len(data["courses"]),
                                  lessons=sum(len(c["lessons"]) for c in data["courses"]))
        if kind == "feature_progress":
            proof["feature_progress"] = data
    app._handle_event = handle

    def observe():
        nonlocal last_worker, stop_scan_for, switch_after_image
        proof["ticks"] += 1
        if command_file.exists():
            command = read_json(command_file)
            command_file.unlink()
            action = command["action"]
            if action == "scan":
                app.start_scan()
            elif action == "samples":
                historic = read_json(next((ROOT / ".local/phase3_output/雨课堂习题下载").glob("任务清单_*.json")))
                app.clear_selection()
                for status in ("complete", "no_images"):
                    record = next(l for l in historic["lessons"].values() if l["status"] == status)
                    app.toggle(app.lesson_iid((record["course_id"], record["lesson_id"])))
            elif action == "download":
                app.start_download()
            elif action == "switch_after_image":
                switch_after_image = command["account_id"]
            elif action == "switch":
                stop_scan_for = command["account_id"]
                app.switch_account(stop_scan_for)
                if app.account["id"] == stop_scan_for and app.worker.running:
                    app.stop()
                    stop_scan_for = None
            elif action == "close":
                app.close()
            proof["commands"].append(dict(action=action, status=app.status.get()))
        if switch_after_image and app.account and app.account["id"] == prior["new_account_id"]:
            output = app.accounts.image_directory(app.account, app.save_dir.get())
            count = len(list(output.rglob("习题_*.jpg")))
            if count:
                proof["files_at_switch_request"] = count
                stop_scan_for = switch_after_image
                app.switch_account(switch_after_image)
                switch_after_image = None
        if app.worker is not last_worker:
            proof["switches"].append(dict(target=app.account["id"], old_worker_alive=last_worker.running,
                loaded_courses=len(app.catalog["courses"]) if app.catalog else 0,
                selected=len(app.selection.selected), target_scan_started=app.worker.mode == "scan" and app.worker.running))
            last_worker = app.worker
        if stop_scan_for and app.account and app.account["id"] == stop_scan_for and app.worker.running:
            app.stop()
            stop_scan_for = None
        proof.update(active_id=app.account["id"] if app.account else None,
            running=app.worker.running, waiting_human=app.waiting_human, pending=app.pending_account,
            status=app.status.get(), metrics={k:v.get() for k,v in app.metrics.items()},
            selected=len(app.selection.selected), callback_errors=app.callback_errors,
            ui_thread=app.ui_thread, worker_thread=app.worker.thread.ident if app.worker.thread else None)
        write_json(directory / "acceptance_live.json", proof)
    def tick():
        try:
            observe()
        except OSError as exc:
            # External inspection tools on Windows can briefly deny replace or
            # deletion of this probe's JSON. Retry the observer on its next tick;
            # never turn an observer IO failure into a product GUI exception.
            proof["observer_io_errors"].append(type(exc).__name__)
        finally:
            if not app.closing:
                root.after(50, tick)
    root.after(50, tick)
    if not app.catalog or app.catalog["status"] != "complete":
        root.after(200, app.start_scan)
    root.mainloop()
    proof.update(closed=True, worker_alive_after_close=app.worker.running)
    write_json(directory / "acceptance_live.json", proof)


if __name__ == "__main__":
    main()
