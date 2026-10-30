"""Native GUI naming inspection in an isolated, empty local project."""
import sys
import tkinter as tk
from pathlib import Path
from threading import get_ident

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ykt.gui import CourseApp
from ykt.storage import write_json


def main():
    base=ROOT/'.local/v23'
    project=base/'gui_project'
    project.mkdir(exist_ok=True)
    root=tk.Tk()
    app=CourseApp(root,project)
    root.title('雨课堂 V2.3 命名规则验收')
    proof=dict(schema_version=1,ticks=0,modes_seen=[],ui_thread=get_ident(),initial_mode=app.naming_mode.get())
    def save():
        write_json(base/'gui_verified.json',proof)
    def observe():
        proof['ticks']+=1
        mode=app.naming_mode.get()
        if mode not in proof['modes_seen']:proof['modes_seen'].append(mode)
        proof.update(mode=mode,worker_mode=app.worker.naming_control.get(),callback_errors=list(app.callback_errors),
                     naming_radios=len(app.naming_radios),tree_height=app.tree.winfo_height())
        if proof['ticks']%5==0:save()
        root.after(100,observe)
    def close():
        proof.update(closed=True,worker_running=app.worker.running)
        save()
        app.close()
    root.protocol('WM_DELETE_WINDOW',close)
    root.after(150,observe)
    root.mainloop()
    print('NAMING_GUI_CLOSED',flush=True)


if __name__=='__main__':main()
