"""Optional real-window verification: observe UI state locally without driving it.

Use the normal visible controls to scan, stop, select and close. No mock backend.
"""

import sys
import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ykt.gui import CourseApp
from ykt.storage import write_json


def main():
    root = tk.Tk()
    app = CourseApp(root, ROOT)
    history = []
    ticks = 0
    running_ticks = 0
    last_state = None
    last_snapshot = {}

    def observe():
        nonlocal ticks, running_ticks, last_state, last_snapshot
        ticks += 1
        running = app.worker.running
        running_ticks += running
        state = (running, app.waiting_human, app.status.get())
        if state != last_state:
            history.append(dict(running=running, waiting_human=app.waiting_human,
                                status=app.status.get()))
            last_state = state
        last_snapshot = dict(
            schema_version=1, observed_at=datetime.now(timezone.utc).isoformat(),
            ticks=ticks, running_ticks=running_ticks, running=running,
            waiting_human=app.waiting_human, status=app.status.get(),
            metrics={key: value.get() for key, value in app.metrics.items()},
            selected=len(app.selection.selected),
            tree_courses=len(app.tree.get_children()),
            tree_lessons=sum(len(app.tree.get_children(iid)) for iid in app.tree.get_children()),
            first_course_state=(app.selection.course_state(str(app.selection.courses[0]["id"]))
                                if app.selection.courses else None),
            save_directory=app.save_dir.get(),
            callback_errors=app.callback_errors, ui_thread=app.ui_thread,
            diagnostic=app.worker.diagnostic,
            worker_thread=app.worker.thread.ident if app.worker.thread else None,
            download_disabled=app.download_button.instate(("disabled",)), history=history)
        last_snapshot["status_visible"] = (
            app.status_label.winfo_rooty() + app.status_label.winfo_height()
            <= root.winfo_rooty() + root.winfo_height())
        write_json(ROOT / ".local" / "phase2_ui_verification.json", last_snapshot)
        root.after(250, observe)

    root.after(250, observe)
    if "--scan" in sys.argv:
        def start_real_scan():
            if app.selection.courses and app.selection.courses[0]["lessons"]:
                course = app.selection.courses[0]
                app.toggle(app.lesson_iid((str(course["id"]), str(course["lessons"][0]["id"]))))
            app.start_scan()
        root.after(500, start_real_scan)
    root.mainloop()
    last_snapshot["window_closed"] = True
    last_snapshot["worker_alive_after_close"] = app.worker.running
    write_json(ROOT / ".local" / "phase2_ui_verification.json", last_snapshot)


if __name__ == "__main__":
    main()
