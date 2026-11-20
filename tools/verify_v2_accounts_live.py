"""Visible real GUI observer: independent login -> live scan, no fake data."""
import sys
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ykt.accounts import Accounts
from ykt.gui import CourseApp
from ykt.storage import write_json


def main():
    origin = "https://changjiang.yuketang.cn"
    accounts = Accounts(ROOT, origin)
    previous = accounts.get()
    new = accounts.add("阶段1独立登录验证")
    output = ROOT / ".local/v2_stage1/new_account_output"
    output.mkdir(parents=True, exist_ok=True)
    accounts.update(new["id"], save_directory=str(output))
    root = tk.Tk()
    app = CourseApp(root, ROOT)
    ticks = 0
    proof = dict(schema_version=1, new_account_id=new["id"], previous_account_id=previous["id"] if previous else None,
                 previous_owner=previous.get("owner") if previous else None,
                 new_profile_initially_absent=not (accounts.site_dir(new) / "browser").exists())
    def observe():
        nonlocal ticks
        ticks += 1
        proof.update(ticks=ticks, active_id=app.account["id"] if app.account else None,
            running=app.worker.running, waiting_human=app.waiting_human,
            callback_errors=app.callback_errors, status=app.status.get(),
            metrics={k:v.get() for k,v in app.metrics.items()},
            catalog_owner=app.catalog.get("owner_fingerprint") if app.catalog else None,
            courses=len(app.catalog["courses"]) if app.catalog else 0,
            lessons=sum(len(c["lessons"]) for c in app.catalog["courses"]) if app.catalog else 0,
            ui_thread=app.ui_thread, worker_thread=app.worker.thread.ident if app.worker.thread else None)
        write_json(ROOT / ".local/v2_stage1/gui_live.json", proof)
        root.after(250, observe)
    root.after(500, lambda: app.switch_account(new["id"]))
    root.after(250, observe)
    root.mainloop()
    proof.update(closed=True, worker_alive_after_close=app.worker.running)
    write_json(ROOT / ".local/v2_stage1/gui_live.json", proof)
    # Keep the new account for user review; restore their original default.
    if previous:
        accounts.activate(previous["id"])


if __name__ == "__main__":
    main()
