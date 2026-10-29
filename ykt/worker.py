"""Browser worker communicates only through Queue and threading.Event."""

from copy import deepcopy
from pathlib import Path
from queue import Queue
from threading import Event, Thread
from playwright.sync_api import TimeoutError

from . import selectors as S
from .browser import NeedsHuman, Stopped, open_browser
from .scanner import scan
from .downloader import download
from .files import FileProblem
from .tasks import TaskLedger


class ScanWorker:
    def __init__(self, origin: str, site_dir: Path, channel=None, account_id=None, expected_owner=None,
                 layout="legacy"):
        self.origin = origin
        self.site_dir = site_dir
        self.channel = channel
        self.events = Queue()
        self.stop_event = Event()
        self.resume_event = Event()
        self.thread = None
        self.diagnostic = None
        self.mode = "scan"
        self.account_id = account_id
        self.expected_owner = expected_owner
        self.ledger = None
        self.layout = layout

    @property
    def running(self):
        return self.thread is not None and self.thread.is_alive()

    def post(self, kind, data):
        # The scanner continues mutating its records after each report. The UI
        # must receive an independent snapshot rather than shared mutable state.
        self.events.put((kind, deepcopy(data)))

    def start(self):
        if self.running:
            return False
        self.stop_event.clear()
        self.resume_event.clear()
        self.mode = "scan"
        self.thread = Thread(target=self._run, name="ykt-browser-worker", daemon=False)
        self.thread.start()
        return True

    def start_download(self, tasks, directory, owner, options=None):
        if self.running or not tasks:
            return False
        if self.expected_owner is not None and owner != self.expected_owner:
            self.post("error", "[习题图片] 任务账号与当前本地账号绑定不一致，请重新扫描")
            return False
        options = dict(options) if options is not None else {"quiz_images": True, "quiz_pdf": False}
        if options.get("courseware_pdf") or not (options.get("quiz_images") or options.get("quiz_pdf")):
            self.post("error", "请选择习题图片或习题PDF；课件PDF尚未实现")
            return False
        if options.get("quiz_pdf") and not self.account_id:
            self.post("error", "PDF任务需要本地账号ID，请从GUI启动")
            return False
        request = dict(tasks=deepcopy(tasks), directory=Path(directory), owner=owner, options=options)
        self.stop_event.clear()
        self.resume_event.clear()
        self.mode = "download"
        self.thread = Thread(target=self._run_download, args=(request,),
                             name="ykt-download-worker", daemon=False)
        self.thread.start()
        return True

    def stop(self):
        self.stop_event.set()
        self.resume_event.set()

    def start_delete(self, root, account_id):
        if self.running:
            return False
        self.stop_event.clear()
        self.mode = "account_delete"
        def remove():
            from .accounts import Accounts
            try:
                Accounts(root, self.origin).delete(account_id)
                self.post("account_deleted", account_id)
            except Exception:
                self.post("error", "删除未完成：资料可能正在使用或路径异常；下载文件未删除")
            finally:
                self.post("finished", None)
        self.thread = Thread(target=remove, name="ykt-account-delete", daemon=False)
        self.thread.start()
        return True

    def resume(self):
        self.resume_event.set()

    def _run(self):
        emit = lambda message: self.post("log", message)
        try:
            with open_browser(self.site_dir / "browser", emit, self.channel) as (_, page):
                while not self.stop_event.is_set():
                    try:
                        result = scan(
                            page, self.origin, self.site_dir / "courses.json",
                            self.stop_event, emit,
                            on_progress=lambda value: self.post("progress", value),
                            expected_owner=self.expected_owner)
                        self.post("result", result)
                        return
                    except NeedsHuman as exc:
                        if page.is_closed():
                            self.post("error", "浏览器已关闭，请重新扫描")
                            return
                        self.resume_event.clear()
                        self.post("needs_human", str(exc))
                        # No Tk calls, console input or automatic challenge actions.
                        while not self.resume_event.wait(0.2):
                            if self.stop_event.is_set():
                                return
                        if self.stop_event.is_set():
                            return
                        self.post("resuming", "重新验证登录并扫描课程")
                    except TimeoutError:
                        # Whitelisted scalar state only, for local diagnostics.
                        # Never retain raw browser errors or full page/model data.
                        if page.locator(S.INDEX_VIEW).count() == 1:
                            self.diagnostic = page.locator(S.INDEX_VIEW).evaluate(
                                """e=>{let v=e.__vue__;return {
                                  active:v.activeTab, requested:v.tab2Request,
                                  loading:v.isLoading, original:v.originalTableData2?.length,
                                  shown:v.tableData2?.length,
                                  rendered:document.querySelectorAll('#pane-student .lesson-cardS').length
                                }}""")
                        raise
        except Stopped:
            self.post("stopped", "任务已停止")
        except NeedsHuman as exc:
            self.post("error", str(exc))
        except Exception as exc:
            self.post("error", "扫描异常（{}），请检查浏览器或本地环境".format(
                type(exc).__name__))
        finally:
            self.post("finished", None)

    def _run_download(self, request):
        if self.account_id is None:
            self._run_download_impl(request)
            return
        try:
            with TaskLedger(self.site_dir, self.account_id, self.origin) as ledger:
                self.ledger = ledger
                ledger.begin(request["tasks"], request["options"])
                self._run_download_impl(request)
                ledger.interrupt("stopped" if self.stop_event.is_set() else "failed",
                                 "任务未完成，请核验登录或资源后重试")
                self.post("feature_progress", ledger.counts())
        except Exception as exc:
            self.post("error", "[任务状态] 无法保存或读取（{}），原文件已保留".format(type(exc).__name__))
            self.post("finished", None)
        finally:
            self.ledger = None

    def _lesson_done(self, task, lesson):
        if self.ledger is not None:
            row = self.ledger.lesson(task, lesson)
            self.post("resource_state", row)
            self.post("feature_progress", self.ledger.counts())

    def _feature_done(self, task, feature, result):
        row = self.ledger.feature(task, feature, result)
        self.post("resource_state", row)
        self.post("feature_progress", self.ledger.counts())

    def _run_download_impl(self, request):
        emit = lambda message: self.post("log", message)
        try:
            with open_browser(self.site_dir / "browser", emit, self.channel) as (context, page):
                while not self.stop_event.is_set():
                    try:
                        if request["options"].get("quiz_pdf"):
                            from .quiz_export import export_quizzes
                            result = export_quizzes(context, page, self.origin, request,
                                self.site_dir, self.account_id, self.layout, self.stop_event, emit,
                                self._lesson_done, self._feature_done,
                                lambda value: self.post("download_progress", value))
                        else:
                            result = download(context, page, self.origin, request["tasks"],
                                              request["directory"], request["owner"], self.stop_event,
                                              emit, lambda value: self.post("download_progress", value),
                                              on_lesson=self._lesson_done if self.ledger else None, layout=self.layout)
                        self.post("download_result", result)
                        return
                    except NeedsHuman as exc:
                        if page.is_closed():
                            self.post("error", "浏览器已关闭，请重新启动下载")
                            return
                        self.resume_event.clear()
                        self.post("needs_human", str(exc))
                        while not self.resume_event.wait(0.2):
                            if self.stop_event.is_set():
                                return
                        if self.stop_event.is_set():
                            return
                        self.post("resuming", "重新核验账号并刷新资源；已验证完整的文件会跳过")
        except Stopped:
            self.post("stopped", "下载任务已停止")
        except (NeedsHuman, FileProblem) as exc:
            self.post("error", str(exc))
        except Exception as exc:
            self.post("error", "下载异常（{}），请检查浏览器或本地环境".format(type(exc).__name__))
        finally:
            self.post("finished", None)
