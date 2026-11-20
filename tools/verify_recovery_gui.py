"""Real stopped manifest -> native GUI retry. No substitute website data."""
import sys
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ykt.gui import CourseApp
from ykt.recovery import unfinished
from ykt.storage import read_json, write_json


def main():
    root = tk.Tk()
    app = CourseApp(root, ROOT)
    previous = app.save_dir.get()
    directory = ROOT / ".local" / "phase4_browser_closed"
    app.set_directory(str(directory))
    proof = dict(schema_version=1, saw_running=False)

    def observe():
        proof["saw_running"] |= app.worker.running
        proof.update(selected=len(app.selection.selected), running=app.worker.running,
                     metrics={k: v.get() for k, v in app.metrics.items()},
                     status=app.status.get(), callback_errors=app.callback_errors)
        if proof["saw_running"] and not app.worker.running:
            manifest = read_json(next((directory / "雨课堂习题下载").glob("任务清单_*.json")))
            proof["last_run"] = manifest["last_run"]
            proof["remaining_unfinished"] = len(unfinished(directory, app.catalog["owner_fingerprint"], app.worker.origin))
        write_json(ROOT / ".local" / "phase4_recovery_gui_verified.json", proof)
        root.after(250, observe)

    root.after(500, app.show_unfinished)
    root.after(250, observe)
    root.mainloop()
    proof.update(window_closed=True, worker_alive_after_close=app.worker.running)
    write_json(ROOT / ".local" / "phase4_recovery_gui_verified.json", proof)
    write_json(ROOT / ".local" / "gui_settings.json", dict(schema_version=1, save_directory=previous))


if __name__ == "__main__":
    main()
