"""Read the platform's already-authorized lesson report and quiz images."""

import time
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import Error, TimeoutError

from . import selectors as S
from .browser import NeedsHuman, PageChanged, check_stop, navigate, wait_condition
from .scanner import valid_id


class ReportWatch:
    def __init__(self, page, origin, lesson_id):
        self.page = page
        self.host = urlsplit(origin).hostname
        self.lesson_id = lesson_id
        self.count = None
        self.quiz_count = None
        self.quiz_ids = set()
        self.detail = False
        self.info = None
        self.blocked = False
        self.error = False

    def __enter__(self):
        self.page.on("response", self.capture)
        return self

    def __exit__(self, *args):
        self.page.remove_listener("response", self.capture)

    def capture(self, response):
        url = urlsplit(response.url)
        name = url.path.removeprefix(S.REPORT_API_PREFIX) if url.path.startswith(S.REPORT_API_PREFIX) else ""
        if (url.hostname != self.host or name not in S.REPORT_API_NAMES or
                parse_qs(url.query).get("lesson_id") != [self.lesson_id]):
            return
        if response.status in (401, 403, 429):
            self.blocked = True
            return
        try:
            payload = response.json()
            if response.status == 200 and payload.get("code") != 0:
                self.blocked = True
                return
            if response.status != 200:
                self.error = True
                return
            data = payload["data"]
            if name == "review":
                rows = data["timelineList"]
                if not isinstance(rows, list):
                    self.error = True
                    return
                self.count = len(rows)
                # Real review timeline repeats the same slide across display
                # events: 24 sent events correspond to 14 unique quiz slides.
                self.quiz_ids = {str(row["id"]) for row in rows
                                 if row.get("sendProblem") is True and row.get("hasProblem") is True}
                self.quiz_count = len(self.quiz_ids)
            elif name == "detail":
                self.detail = isinstance(data.get("problemStatistics"), dict)
            elif name == "lesson-info":
                self.info = (str(data["lessonId"]), str(data["classroomId"]))
        except (Error, ValueError, KeyError, TypeError, AttributeError):
            self.error = True

    def check(self):
        if self.blocked or getattr(self.page, "_ykt_access_blocked", False):
            raise NeedsHuman("习题报告要求重新登录、授权或限流处理，请在浏览器人工检查")
        if self.error:
            raise PageChanged("习题报告接口未返回已验证的成功结构")


def _state(frame):
    if frame.locator(S.REPORT_VIEW).count() != 1:
        return None
    return frame.locator(S.REPORT_VIEW).evaluate(S.REPORT_STATE)


def _wait_state(page, frame, watch, course_id, stop, selected=False, all_slides=False):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        check_stop(stop)
        state = _state(frame)  # Also pumps response events on the owning thread.
        watch.check()
        if (state and watch.detail and watch.info == (watch.lesson_id, course_id) and
                watch.count is not None and state["lesson_id"] == watch.lesson_id and
                state["course_id"] == course_id and state["all"] == watch.count):
            if all_slides:
                if state["selected"] == 0 and state["shown"] == watch.count:
                    return state
            elif not selected or (state["selected"] == 1 and state["shown"] == watch.quiz_count and
                                {s["slide_id"] for s in state["slides"]} == watch.quiz_ids):
                return state
        if stop.wait(0.1):
            check_stop(stop)
    raise TimeoutError("习题报告加载状态等待超时")


def extract_lesson(page, origin, task, stop, emit):
    """Returns ordered authorized resource candidates; never persists URLs."""
    cid = valid_id(task["course_id"])
    lesson = task["lesson"]
    if lesson.get("is_finished") is False:
        raise PageChanged("课堂尚未结束，平台习题报告暂不可用；请课后重新扫描并重试")
    cw = valid_id(lesson["courseware_id"])
    lid = valid_id(lesson["id"])
    target = origin + S.REPORT_PATH.format(course_id=cid, courseware_id=cw, lesson_id=lid)
    for attempt in range(4):
        try:
            with ReportWatch(page, origin, cw) as watch:
                # A single shared page retry budget covers navigation, rendering
                # and filtering, rather than nesting two independent budgets.
                navigate(page, target, stop, emit, retries=0)
                # An attached iframe can still be about:blank. Wait for its real
                # address before judging authorization; model/DOM readiness is
                # checked separately below. Foreign origins are still rejected.
                wait_condition(page, S.REPORT_FRAME_READY, stop)
                frame = page.locator(S.REPORT_IFRAME).element_handle().content_frame()
                if frame is None or urlsplit(frame.url).hostname != urlsplit(origin).hostname:
                    raise NeedsHuman("课时报告框架尚未就绪或跳转，请人工检查")
                state = _wait_state(page, frame, watch, cid, stop)
                tab = frame.locator(S.QUIZ_TABS).get_by_text(S.QUIZ_TAB_NAME, exact=True)
                if watch.quiz_count == 0:
                    if state["sent"] is not False or tab.is_visible():
                        raise PageChanged("无习题记录与页面筛选状态不一致，未宣称无图片")
                    return dict(resources=[], unsupported=[], pages=0)
                if not tab.is_visible():
                    raise PageChanged("报告包含习题，但习题筛选不可见")
                try:
                    tab.click(timeout=10000)
                except TimeoutError:
                    raise NeedsHuman("习题筛选不可操作，请人工检查页面遮挡提示或安全验证") from None
                state = _wait_state(page, frame, watch, cid, stop, selected=True)
                emit("已核对 {} 张习题页".format(watch.quiz_count))
                items = frame.locator(S.QUIZ_ITEMS)
                if items.count() != watch.quiz_count:
                    raise PageChanged("习题筛选模型与页面数量不一致")
                resources, unsupported = [], []
                for index, slide in enumerate(state["slides"]):
                    check_stop(stop)
                    watch.check()
                    if slide["sent"] is not True or slide["has_problem"] is not True:
                        raise PageChanged("筛选区域含非习题页，已停止提取")
                    item = items.nth(index)
                    item.scroll_into_view_if_needed(timeout=10000)
                    data = item.evaluate(S.QUIZ_RESOURCE_DATA)
                    unsupported.extend(data["unsupported"])
                    if not data["resources"]:
                        unsupported.append("习题页没有可提取图片，未导出截图")
                    for resource in data["resources"]:
                        candidates = resource["candidates"]
                        # This actual model cover equals the 1280x960 preview.
                        # It is a provided URL, never a guessed resize/original URL.
                        if not candidates and len(data["resources"]) == 1 and slide.get("cover"):
                            candidates.append(slide["cover"])
                        candidates = [url for url in candidates
                                      if urlsplit(url).scheme in ("http", "https", "data", "blob")]
                        if not candidates:
                            unsupported.append("图片没有受支持的资源入口")
                            continue
                        resources.append(dict(candidates=candidates, slide_id=slide["slide_id"],
                                              page=slide["page"], frame=frame))
                return dict(resources=resources, unsupported=unsupported, pages=watch.quiz_count)
        except TimeoutError:
            if attempt == 3:
                raise PageChanged("习题页面连续加载超时，请重新运行该课时") from None
            emit("习题页面加载超时，重试 {}/3".format(attempt + 1))
            if stop.wait(attempt + 1):
                check_stop(stop)
