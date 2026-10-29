"""Tk/ttk desktop view. All widget access belongs to the Tk main thread."""

import tkinter as tk
from datetime import datetime, timedelta, timezone
from pathlib import Path
from queue import Empty
from threading import get_ident
from tkinter import filedialog, ttk
from urllib.parse import urlsplit

from .selection import CourseSelection
from .storage import read_json, write_json
from .worker import ScanWorker
from .recovery import unfinished
from .files import FileProblem

STATUS = {"complete": "扫描完成", "pending": "待扫描", "scanning": "扫描中",
          "failed": "扫描失败", "incomplete": "未完成"}
RESULT_STATUS = {"complete": "扫描完成", "partial": "部分失败", "stopped": "已停止",
                 "running": "扫描中", "needs_human": "等待人工处理"}


class CourseApp:
    def __init__(self, root, project_root: Path, origin="https://changjiang.yuketang.cn",
                 channel=None):
        self.root = root
        self.ui_thread = get_ident()
        self.project_root = project_root
        self.site_dir = project_root / ".local" / urlsplit(origin).hostname
        self.worker = ScanWorker(origin, self.site_dir, channel)
        self.selection = CourseSelection()
        self.nodes = {}
        self.catalog = None
        self.closing = False
        self.waiting_human = False
        self.callback_errors = []
        self.root.report_callback_exception = self._callback_error
        self.root.title("雨课堂习题图片下载工具")
        self.root.geometry("1120x760")
        self.root.minsize(900, 620)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.status = tk.StringVar(value="就绪")
        self.catalog_info = tk.StringVar(value="尚无课程，请扫描课程")
        self.selected_info = tk.StringVar(value="已勾选 0 个课时")
        self.save_dir = tk.StringVar()
        self.current_course = tk.StringVar(value="当前课程：—")
        self.current_lesson = tk.StringVar(value="当前课时：—")
        self.task_kind = tk.StringVar(value="任务类型：未运行")
        self.metrics = {key: tk.IntVar(value=0)
                        for key in ("total", "completed", "success", "failed")}
        self._build()
        self._load_settings()
        self.load_cache()
        self.root.after(80, self._poll)

    def _assert_ui(self):
        if get_ident() != self.ui_thread:
            raise RuntimeError("GUI 更新必须在主线程执行")

    def _checkbox_images(self):
        size = max(16, round(float(self.root.tk.call("tk", "scaling")) * 11))
        images = {}
        for name in ("unchecked", "checked", "partial", "empty"):
            image = tk.PhotoImage(master=self.root, width=size, height=size)
            color = "#adb5bd" if name == "empty" else "#65758b"
            image.put(color, to=(1, 1, size - 2, size - 2))
            image.put("#f8fafc", to=(2, 2, size - 3, size - 3))
            if name in ("checked", "partial"):
                image.put("#2563eb", to=(2, 2, size - 3, size - 3))
            if name == "partial":
                image.put("white", to=(4, size // 2 - 1, size - 5, size // 2 + 1))
            elif name == "checked":
                for x in range(4, size - 5):
                    y = (size // 2 + x - 4) if x < size // 2 - 1 else (size - x - 2)
                    for dy in (-1, 0, 1):
                        if 2 <= y + dy < size - 3:
                            image.put("white", (x, y + dy))
            images[name] = image
        return images

    def _build(self):
        style = ttk.Style(self.root)
        style.configure("Treeview", rowheight=28, font=("Microsoft YaHei UI", 10))
        outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(4, weight=1)
        ttk.Label(outer, text="雨课堂习题图片下载工具",
                  font=("Microsoft YaHei UI", 16, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(outer, text="仅保存当前账号可访问的课堂习题图片 · 完整文件自动跳过",
                  foreground="#526174").grid(row=1, column=0, sticky="w", pady=(3, 10))
        actions = ttk.Frame(outer)
        actions.grid(row=2, column=0, sticky="ew")
        self.scan_button = ttk.Button(actions, text="扫描课程", command=self.start_scan)
        self.scan_button.pack(side="left")
        self.cache_button = ttk.Button(actions, text="读取缓存", command=self.load_cache)
        self.cache_button.pack(side="left", padx=6)
        self.stop_button = ttk.Button(actions, text="停止任务", command=self.stop, state="disabled")
        self.stop_button.pack(side="left")
        self.resume_button = ttk.Button(actions, text="人工处理完成，继续", command=self.resume,
                                        state="disabled")
        self.resume_button.pack(side="left", padx=6)
        ttk.Label(actions, textvariable=self.selected_info).pack(side="right")
        ttk.Label(outer, textvariable=self.catalog_info, foreground="#526174").grid(
            row=3, column=0, sticky="w", pady=(8, 5))
        tree_frame = ttk.Frame(outer)
        tree_frame.grid(row=4, column=0, sticky="nsew")
        self.tree = ttk.Treeview(tree_frame, columns=("selected", "status", "detail"),
                                 selectmode="browse", show="tree headings")
        self.tree.heading("#0", text="课程 / 课时（点击方框勾选，空格切换）", anchor="w")
        self.tree.heading("selected", text="已选 / 课时")
        self.tree.heading("status", text="扫描状态")
        self.tree.heading("detail", text="班级 / 上课时间（北京时间）", anchor="w")
        self.tree.column("#0", width=430, minwidth=240)
        self.tree.column("selected", width=95, minwidth=95, stretch=False, anchor="center")
        self.tree.column("status", width=100, minwidth=100, stretch=False, anchor="center")
        self.tree.column("detail", width=400, minwidth=180)
        yscroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        self.images = self._checkbox_images()
        self.tree.bind("<Button-1>", self._tree_click)
        self.tree.bind("<space>", self._tree_space)
        choose = ttk.Frame(outer)
        choose.grid(row=5, column=0, sticky="ew", pady=7)
        ttk.Button(choose, text="全部勾选", command=self.select_all).pack(side="left")
        ttk.Button(choose, text="清空勾选", command=self.clear_selection).pack(side="left", padx=6)
        ttk.Button(choose, text="展开全部", command=lambda: self.expand_all(True)).pack(side="left")
        ttk.Button(choose, text="折叠全部", command=lambda: self.expand_all(False)).pack(side="left", padx=6)
        self.recovery_button = ttk.Button(choose, text="失败 / 未完成…", command=self.show_unfinished)
        self.recovery_button.pack(side="left", padx=(10, 0))
        directory = ttk.Frame(outer)
        directory.grid(row=6, column=0, sticky="ew")
        ttk.Label(directory, text="保存目录").pack(side="left")
        ttk.Entry(directory, textvariable=self.save_dir, state="readonly").pack(
            side="left", fill="x", expand=True, padx=8)
        self.directory_button = ttk.Button(directory, text="选择目录…", command=self.choose_directory)
        self.directory_button.pack(side="left")
        self.download_button = ttk.Button(directory, text="开始下载", command=self.start_download, state="disabled")
        self.download_button.pack(side="left", padx=(8, 0))
        progress = ttk.LabelFrame(outer, text="任务进度", padding=8)
        progress.grid(row=7, column=0, sticky="ew", pady=(10, 6))
        ttk.Label(progress, textvariable=self.task_kind).grid(row=0, column=0, sticky="w", padx=(0, 24))
        for column, (key, label) in enumerate((("total", "总数"), ("completed", "完成"),
                                               ("success", "成功"), ("failed", "失败")), 1):
            cell = ttk.Frame(progress)
            cell.grid(row=0, column=column, padx=(0, 18), sticky="w")
            ttk.Label(cell, text=label + "：").pack(side="left")
            ttk.Label(cell, textvariable=self.metrics[key]).pack(side="left")
        self.progress = ttk.Progressbar(progress, mode="determinate")
        self.progress.grid(row=1, column=0, columnspan=5, sticky="ew", pady=5)
        progress.columnconfigure(0, weight=1)
        ttk.Label(progress, textvariable=self.current_course, wraplength=920).grid(
            row=2, column=0, columnspan=5, sticky="w")
        ttk.Label(progress, textvariable=self.current_lesson, wraplength=920).grid(
            row=3, column=0, columnspan=5, sticky="w")
        log_frame = ttk.Frame(outer)
        log_frame.grid(row=8, column=0, sticky="ew")
        self.log = tk.Text(log_frame, height=6, wrap="word", state="disabled",
                           font=("Microsoft YaHei UI", 9), relief="solid", borderwidth=1)
        log_scroll = ttk.Scrollbar(log_frame, command=self.log.yview)
        self.log.configure(yscrollcommand=log_scroll.set)
        self.log.pack(side="left", fill="x", expand=True)
        log_scroll.pack(side="right", fill="y")
        self.status_label = ttk.Label(outer, textvariable=self.status, foreground="#334155")
        self.status_label.grid(row=9, column=0, sticky="w", pady=(6, 0))

    def _callback_error(self, kind, value, traceback):
        self.callback_errors.append(kind.__name__)
        self.status.set("界面操作异常（{}）".format(kind.__name__))
        self._append_log(self.status.get())

    def _append_log(self, message):
        self._assert_ui()
        stamp = datetime.now(timezone(timedelta(hours=8))).strftime("%H:%M:%S")
        self.log.configure(state="normal")
        self.log.insert("end", "[{}] {}\n".format(stamp, message))
        lines = int(self.log.index("end-1c").split(".")[0])
        if lines > 1000:
            self.log.delete("1.0", "{}.0".format(lines - 1000))
        self.log.see("end")
        self.log.configure(state="disabled")

    def _load_settings(self):
        try:
            settings = read_json(self.project_root / ".local" / "gui_settings.json")
            directory = settings.get("save_directory", "")
            if isinstance(directory, str):
                self.save_dir.set(directory)
        except FileNotFoundError:
            pass
        except (ValueError, KeyError, OSError, TypeError):
            self._append_log("目录设置无法读取，请重新选择保存目录")

    def choose_directory(self):
        directory = filedialog.askdirectory(parent=self.root, title="选择习题图片保存目录",
                                             initialdir=self.save_dir.get() or str(self.project_root),
                                             mustexist=True)
        if directory:
            self.set_directory(directory)

    def set_directory(self, directory):
        self._assert_ui()
        path = Path(directory)
        if not path.is_dir():
            self.status.set("请选择已存在的目录")
            return False
        try:
            write_json(self.project_root / ".local" / "gui_settings.json",
                       dict(schema_version=1, save_directory=str(path.resolve())))
        except OSError:
            self.status.set("无法保存目录设置，请检查本地写入权限")
            return False
        self.save_dir.set(str(path.resolve()))
        self.status.set("保存目录已选择")
        self._update_controls()
        return True

    def load_cache(self):
        self._assert_ui()
        if self.worker.running:
            return
        try:
            result = read_json(self.site_dir / "courses.json")
            self._display_catalog(result, cached=True)
            self._append_log("已读取本地课程缓存；本次登录和访问权限尚未重新验证")
        except FileNotFoundError:
            self.status.set("没有扫描缓存，请点击“扫描课程”并人工登录")
        except (KeyError, TypeError, ValueError, OSError):
            self.status.set("缓存无法读取或结构异常，请重新扫描")
            self._append_log(self.status.get())

    def _display_catalog(self, result, cached=False):
        self._assert_ui()
        if result.get("origin") != self.worker.origin:
            raise ValueError("缓存站点不一致")
        self.selection.replace(result)
        self.catalog = result
        self._render_tree()
        lessons = sum(len(c["lessons"]) for c in result["courses"])
        label = RESULT_STATUS.get(result["status"], "状态未知")
        note = "本地缓存，未验证本次登录" if cached else "本次扫描"
        self.catalog_info.set("{} · {} · {} 个课程班级 / {} 个课时".format(
            note, label, len(result["courses"]), lessons))

    @staticmethod
    def course_iid(course_id):
        return "course:" + str(course_id)

    @staticmethod
    def lesson_iid(key):
        return "lesson:{}:{}".format(*key)

    @staticmethod
    def _lesson_time(lesson):
        try:
            return datetime.fromtimestamp(lesson["created_at"] / 1000,
                                          timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            return "—"

    def _render_tree(self):
        opened = {iid for iid in self.tree.get_children() if self.tree.item(iid, "open")}
        focus = self.tree.focus()
        yview = self.tree.yview()
        initial = not self.tree.get_children()
        self.tree.delete(*self.tree.get_children())
        self.nodes.clear()
        for index, course in enumerate(self.selection.courses):
            cid = str(course["id"])
            iid = self.course_iid(cid)
            self.nodes[iid] = ("course", cid)
            name = course["name"] + ("  [归档]" if course.get("archived") else "")
            self.tree.insert("", "end", iid=iid, text=name,
                             open=iid in opened or (initial and index == 0),
                             values=("", STATUS.get(course["status"], "未知"),
                                     course.get("class_name", "")))
            for lesson in course["lessons"]:
                key = (cid, str(lesson["id"]))
                liid = self.lesson_iid(key)
                self.nodes[liid] = ("lesson", key)
                self.tree.insert(iid, "end", iid=liid, text=lesson["name"],
                                 values=("", "进行中" if lesson.get("is_finished") is False else "",
                                         self._lesson_time(lesson)))
        self._refresh_checks()
        if focus in self.nodes:
            self.tree.focus(focus)
            self.tree.selection_set(focus)
        if yview:
            self.tree.yview_moveto(yview[0])

    def _refresh_checks(self):
        self._assert_ui()
        selected = self.selection.selected
        for course in self.selection.courses:
            cid = str(course["id"])
            count = 0
            for lesson in course["lessons"]:
                key = (cid, str(lesson["id"]))
                checked = key in selected
                count += checked
                iid = self.lesson_iid(key)
                self.tree.item(iid, image=self.images["checked" if checked else "unchecked"])
                self.tree.set(iid, "selected", "已勾选" if checked else "未勾选")
            state = self.selection.course_state(cid) if course["lessons"] else "empty"
            iid = self.course_iid(cid)
            self.tree.item(iid, image=self.images[state])
            self.tree.set(iid, "selected", "{} / {}".format(count, len(course["lessons"])))
        self.selected_info.set("已勾选 {} 个课时".format(len(self.selection.selected)))
        self._update_controls()

    def toggle(self, iid):
        self._assert_ui()
        if self.worker.running and self.worker.mode == "download":
            self.status.set("下载任务已固定，请停止或等待结束后修改勾选")
            return
        kind, key = self.nodes[iid]
        if kind == "course":
            self.selection.toggle_course(key)
        else:
            self.selection.toggle_lesson(key)
        self._refresh_checks()

    def _tree_click(self, event):
        iid = self.tree.identify_row(event.y)
        if iid and "image" in self.tree.identify_element(event.x, event.y):
            self.tree.focus_set()
            self.tree.focus(iid)
            self.tree.selection_set(iid)
            self.toggle(iid)
            return "break"

    def _tree_space(self, event):
        iid = self.tree.focus()
        if iid in self.nodes:
            self.toggle(iid)
        return "break"

    def select_all(self):
        if self.worker.running and self.worker.mode == "download":
            return
        self.selection.select_all()
        self._refresh_checks()

    def clear_selection(self):
        if self.worker.running and self.worker.mode == "download":
            return
        self.selection.clear()
        self._refresh_checks()

    def expand_all(self, opened):
        for iid in self.tree.get_children():
            self.tree.item(iid, open=opened)

    def start_scan(self):
        self._assert_ui()
        if self.closing or self.worker.running:
            return
        self.waiting_human = False
        for var in self.metrics.values():
            var.set(0)
        self.progress.configure(value=0, maximum=1)
        self.current_course.set("当前课程：等待课程目录")
        self.current_lesson.set("当前课时：—（课程扫描不进入习题）")
        self.task_kind.set("任务类型：课程扫描")
        self.status.set("扫描中；如浏览器显示登录页面，请人工登录")
        self._append_log("开始扫描课程，已加载的目录继续保留供查看")
        self.worker.start()
        self._update_controls()

    def stop(self):
        self.worker.stop()
        self.waiting_human = False
        self.status.set("正在安全停止，等待当前浏览器操作结束并保存结果…")
        self._update_controls()

    def start_download(self):
        self._assert_ui()
        if self.closing or self.worker.running:
            return
        tasks = self.selection.tasks()
        if not tasks or not self.catalog or not self.catalog.get("owner_fingerprint"):
            self.status.set("请先扫描或读取缓存，并勾选目标课时")
            return
        if not self.save_dir.get() or not Path(self.save_dir.get()).is_dir():
            self.status.set("请选择已存在的保存目录")
            return
        for var in self.metrics.values():
            var.set(0)
        self.metrics["total"].set(len(tasks))
        self.progress.configure(value=0, maximum=len(tasks))
        self.current_course.set("当前课程：等待账号核验")
        self.current_lesson.set("当前课时：—")
        self.task_kind.set("任务类型：图片下载（按课时计数）")
        self.catalog_info.set("课程目录来自缓存，下载时逐课时核验访问权限")
        self.waiting_human = False
        self.status.set("下载中；正在核验登录账号与所选课时")
        self._append_log("开始处理 {} 个课时；只保存习题区域图片".format(len(tasks)))
        self.worker.start_download(tasks, self.save_dir.get(), self.catalog["owner_fingerprint"])
        self._update_controls()

    def resume(self):
        if self.worker.running and self.waiting_human:
            self.waiting_human = False
            self.worker.resume()
            self.status.set("继续验证页面状态…")
            self._update_controls()

    def select_unfinished(self, rows):
        self._assert_ui()
        if self.worker.running or self.closing:
            return
        wanted = {(row["course_id"], row["lesson_id"]) for row in rows}
        self.selection.clear()
        for course in self.selection.courses:
            for lesson in course["lessons"]:
                key = (str(course["id"]), str(lesson["id"]))
                if key in wanted:
                    self.selection.toggle_lesson(key)
        self._refresh_checks()
        self.status.set("已勾选 {} 个未完成课时，点击“开始下载”重新处理；未出现在目录中的课时请先重扫".format(
            len(self.selection.selected)))

    def show_unfinished(self):
        self._assert_ui()
        if self.worker.running or self.closing:
            return
        if not self.catalog or not self.save_dir.get():
            self.status.set("请先读取课程目录并选择原保存目录")
            return
        try:
            rows = unfinished(self.save_dir.get(), self.catalog["owner_fingerprint"], self.worker.origin)
        except FileNotFoundError:
            self.status.set("当前目录还没有此账号的下载任务清单")
            return
        except (FileProblem, OSError, KeyError, ValueError):
            self.status.set("任务清单无法读取；请保留原文件并检查，或选择其他目录")
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("失败和未完成的课时")
        dialog.geometry("780x460")
        dialog.transient(self.root)
        panel = ttk.Frame(dialog, padding=12)
        panel.pack(fill="both", expand=True)
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(1, weight=1)
        ttk.Label(panel, text="读取原保存目录的任务记录；重新下载时仍会校验并跳过完整文件。").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        body = ttk.Frame(panel)
        body.grid(row=1, column=0, columnspan=2, sticky="nsew")
        text = tk.Text(body, height=12, wrap="word", font=("Microsoft YaHei UI", 10))
        scroll = ttk.Scrollbar(body, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        for row in rows:
            state_label = {"pending": "待处理", "running": "上次任务未结束", "failed": "失败",
                           "stopped": "已停止", "needs_human": "等待人工处理"}.get(row["status"], row["status"])
            text.insert("end", "{} / {}\n状态：{}\n{}\n\n".format(
                row["course_name"], row["lesson_name"], state_label,
                "；".join(row["reasons"]) or "上次任务未处理完毕"))
        if not rows:
            text.insert("end", "任务清单没有失败或未完成课时。若文件后来损坏或丢失，重新勾选下载即可校验并恢复。")
        text.configure(state="disabled")
        def select():
            self.select_unfinished(rows)
            dialog.destroy()
        ttk.Button(panel, text="仅勾选列表课时", command=select,
                   state="normal" if rows else "disabled").grid(row=2, column=0, sticky="w", pady=(10, 0))
        ttk.Button(panel, text="关闭", command=dialog.destroy).grid(row=2, column=1, sticky="e", pady=(10, 0))
        return dialog

    def _handle_event(self, kind, data):
        self._assert_ui()
        if kind == "log":
            self._append_log(data)
        elif kind == "progress":
            self._display_catalog(data["result"])
            for key, var in self.metrics.items():
                var.set(data[key])
            self.progress.configure(maximum=max(data["total"], 1), value=data["completed"])
            self.current_course.set("当前课程：" + data["current_course"])
        elif kind == "result":
            self._display_catalog(data)
            self.status.set(RESULT_STATUS.get(data["status"], data["status"]))
            self._append_log(self.status.get())
        elif kind == "download_progress":
            for key, var in self.metrics.items():
                var.set(data[key])
            self.progress.configure(maximum=max(data["total"], 1), value=data["completed"])
            self.current_course.set("当前课程：" + data["current_course"])
            self.current_lesson.set("当前课时：{}（累计保存 {}，校验跳过 {}，图片失败 {}）".format(
                data["current_lesson"], data["downloaded"], data["skipped"], data["image_failed"]))
        elif kind == "download_result":
            self.status.set({"complete": "下载处理完成", "partial": "下载结束，部分课时失败",
                             "stopped": "下载已停止"}.get(data["status"], "下载任务结束"))
            self._append_log("{}：保存 {} 张，校验跳过 {} 张，图片失败 {} 张，无图片课时 {} 个".format(
                self.status.get(), data["downloaded"], data["skipped"], data["image_failed"], data["no_images"]))
        elif kind == "needs_human":
            self.waiting_human = True
            self.status.set("已暂停：请在浏览器人工处理，再点击“人工处理完成，继续”")
            self._append_log("需要人工处理：" + data)
        elif kind in ("error", "stopped", "resuming"):
            self.waiting_human = False
            self.status.set(data)
            self._append_log(data)
        elif kind == "finished":
            self.waiting_human = False
            if self.worker.stop_event.is_set():
                self.status.set("已停止；已完成文件和记录已保留")

    def _update_controls(self):
        running = self.worker.running
        idle = not running and not self.closing
        self.scan_button.configure(state="normal" if idle else "disabled")
        self.cache_button.configure(state="normal" if idle else "disabled")
        self.recovery_button.configure(state="normal" if idle else "disabled")
        ready = idle and bool(self.selection.selected) and bool(self.save_dir.get())
        self.download_button.configure(state="normal" if ready else "disabled")
        self.directory_button.configure(state="normal" if idle else "disabled")
        self.stop_button.configure(state="normal" if running and not self.worker.stop_event.is_set()
                                   else "disabled")
        self.resume_button.configure(state="normal" if running and self.waiting_human and
                                     not self.worker.stop_event.is_set() else "disabled")

    def _poll(self):
        self._assert_ui()
        for _ in range(200):
            try:
                kind, data = self.worker.events.get_nowait()
            except Empty:
                break
            try:
                self._handle_event(kind, data)
            except (ValueError, KeyError, TypeError) as exc:
                self._callback_error(type(exc), exc, None)
                self.worker.stop()
        self._update_controls()
        if self.closing and not self.worker.running:
            self.root.destroy()
            return
        self.root.after(80, self._poll)

    def close(self):
        self._assert_ui()
        self.closing = True
        if self.worker.running:
            self.stop()
            self.status.set("正在安全停止并关闭，请稍候…")
        else:
            self.root.destroy()


def run_gui(project_root, origin, channel=None):
    root = tk.Tk()
    CourseApp(root, project_root, origin, channel)
    root.mainloop()
