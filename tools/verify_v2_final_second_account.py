"""Manual second-platform-account login, GUI scan, and safe close observer."""
import sys,time
import tkinter as tk
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ykt.accounts import Accounts
from ykt.gui import CourseApp
from ykt.storage import write_json,read_json

def main():
 a=Accounts(ROOT,'https://changjiang.yuketang.cn');previous=a.get();row=a.add('阶段4第二账号验收')
 output=ROOT/'.local/v2_stage4/second_account_output';output.mkdir(exist_ok=True);a.update(row['id'],save_directory=str(output))
 root=tk.Tk();app=CourseApp(root,ROOT);root.title('雨课堂 V2 最终验收：请登录第二个平台账号')
 proof=dict(schema_version=1,account_id=row['id'],previous_id=previous['id'],previous_owner=previous['owner'],initial_profile_absent=not (a.site_dir(row)/'browser').exists(),ticks=0)
 path=ROOT/'.local/v2_stage4/second_account.json'
 def observe():
  proof['ticks']+=1
  proof.update(running=app.worker.running,waiting_human=app.waiting_human,status=app.status.get(),callback_errors=app.callback_errors,
   owner=app.catalog.get('owner_fingerprint') if app.catalog else None,courses=len(app.catalog['courses']) if app.catalog else 0,
   lessons=sum(len(c['lessons']) for c in app.catalog['courses']) if app.catalog else 0,ui_thread=app.ui_thread,worker_thread=app.worker.thread.ident if app.worker.thread else None)
  write_json(path,proof)
  if (ROOT/'.local/v2_stage4/continue_scan.signal').exists() and app.waiting_human:app.resume()
  if (ROOT/'.local/v2_stage4/close_second.signal').exists():app.close();return
  root.after(250,observe)
 root.after(250,observe);root.after(500,lambda:app.switch_account(row['id']))
 try:root.mainloop()
 finally:
  proof.update(closed=True,worker_alive_after_close=app.worker.running);write_json(path,proof);a.activate(previous['id'])
if __name__=='__main__':main()
