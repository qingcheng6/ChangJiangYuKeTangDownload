"""Native Start button acceptance for courseware PDF stop/resume; uses actual account/cache."""
import sys
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ykt.accounts import Accounts
from ykt.gui import CourseApp
from ykt.storage import read_json, write_json


def main():
    store = Accounts(ROOT, "https://changjiang.yuketang.cn")
    known = read_json(ROOT / ".local/v2_stage1/gui_live.json")
    account_id = known["new_account_id"]
    previous = store.get(account_id)["save_directory"]
    root = tk.Tk()
    app = CourseApp(root, ROOT, account_id=account_id)
    root.title("雨课堂课件PDF — 阶段3验收")
    output = ROOT / ".local/v2_stage3/gui_courseware"
    output.mkdir(exist_ok=True)
    app.set_directory(str(output))
    app.export_images.set(False)
    app.export_quiz_pdf.set(False)
    app.export_courseware_pdf.set(True)
    historic = read_json(next((ROOT / ".local/phase3_output/雨课堂习题下载").glob("任务清单_*.json")))
    for status in ("complete",):
        row = next(l for l in historic["lessons"].values() if l["status"] == status)
        app.toggle(app.lesson_iid((row["course_id"], row["lesson_id"])))
    proof = dict(schema_version=1, ticks=0, saw_running=False, stop_requested=False, resumed=False, driver="Tk main-thread callbacks")
    def observe():
        proof["ticks"] += 1
        proof["saw_running"] |= app.worker.running
        proof.update(running=app.worker.running, metrics={k:v.get() for k,v in app.metrics.items()},
            feature_info=app.feature_info.get(), status=app.status.get(), callback_errors=app.callback_errors,
            ui_thread=app.ui_thread, worker_thread=app.worker.thread.ident if app.worker.thread else None,
            image_option=app.export_images.get(), pdf_option=app.export_quiz_pdf.get())
        try:
            write_json(ROOT / ".local/v2_stage3/gui_verified.json", proof)
        except OSError:
            pass  # The probe may be concurrently read by an inspection tool.
        if not proof['stop_requested'] and app.worker.running and '已读取课件页 1/' in app.log.get('1.0','end'):
            proof['stop_requested'] = True
            app.stop()
        elif proof['stop_requested'] and not proof['resumed'] and not app.worker.running and '已停止' in app.status.get():
            proof['stopped_status'] = app.status.get()
            proof['resumed'] = True
            app.start_download()
        elif proof['resumed'] and not app.worker.running and app.metrics['success'].get() == 1:
            proof['final_courseware_state'] = [v for (cid,lid,f),v in app.resources.items() if f=='courseware_pdf']
            root.after(250, app.close)
            return
        if proof['ticks'] > 2400:
            proof['timed_out'] = True
            app.close()
            return
        root.after(100, observe)
    root.after(100, observe)
    root.after(300, app.start_download)
    root.mainloop()
    store.update(account_id, save_directory=previous)
    proof.update(closed=True, worker_alive_after_close=app.worker.running, account_directory_restored=True)
    write_json(ROOT / ".local/v2_stage3/gui_verified.json", proof)


if __name__ == "__main__":
    main()
