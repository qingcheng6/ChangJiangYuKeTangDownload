"""One persistent Playwright context owned by its calling worker thread."""

from contextlib import contextmanager
from pathlib import Path
from threading import Event
from typing import Callable
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import Error, TimeoutError, sync_playwright

from . import selectors as S


class Stopped(Exception):
    pass


class NeedsHuman(Exception):
    pass


class PageChanged(Exception):
    pass


def check_stop(stop: Event) -> None:
    if stop.is_set():
        raise Stopped()


def wait_condition(page, expression, stop: Event, timeout_ms=30000, arg=None):
    """Bound each wait slice so a worker can stop without accessing Tk widgets."""
    import time
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        check_stop(stop)
        if getattr(page, "_ykt_access_blocked", False):
            raise NeedsHuman("平台返回登录、权限或限流限制，请人工检查浏览器")
        if (expression in (S.INDEX_READY, S.COURSE_RENDERED, "() => true") and
                getattr(page, "_ykt_catalog_failed", False)):
            raise PageChanged("课程目录响应异常，未更新扫描结果")
        try:
            # A GUI can cover the browser: default RAF polling may stop in an
            # occluded/background tab even when the actual DOM is already ready.
            # Numeric polling still tests the real condition, not elapsed time.
            return page.wait_for_function(expression, arg=arg, timeout=500, polling=100)
        except TimeoutError:
            continue
    raise TimeoutError("页面状态等待超时")


@contextmanager
def open_browser(profile: Path, emit: Callable[[str], None], channel=None):
    with sync_playwright() as pw:
        kwargs = dict(headless=False, viewport={"width": 1280, "height": 850})
        if channel:
            kwargs["channel"] = channel
        try:
            context = pw.chromium.launch_persistent_context(str(profile), **kwargs)
        except Error:
            if channel:
                raise NeedsHuman("指定浏览器启动失败，请检查安装或关闭占用此会话的窗口") from None
            emit("内置 Chromium 启动失败，尝试已安装的 Chrome（Chromium 内核）")
            try:
                context = pw.chromium.launch_persistent_context(
                    str(profile), channel="chrome", headless=False,
                    viewport={"width": 1280, "height": 850})
            except Error:
                raise NeedsHuman("浏览器启动失败，请检查 Playwright 浏览器安装或会话占用") from None
        try:
            context.set_default_timeout(10000)
            context.set_default_navigation_timeout(30000)
            page = context.pages[0] if context.pages else context.new_page()

            def access_guard(response):
                path = urlsplit(response.url).path
                if (urlsplit(response.url).hostname == urlsplit(page.url).hostname and
                        path == S.COURSE_API_PATH):
                    try:
                        payload = response.json()
                        page._ykt_catalog_failed = (response.status != 200 or
                            payload.get("errcode") != 0 or
                            not isinstance(payload.get("data", {}).get("list"), list))
                        if parse_qs(urlsplit(response.url).query).get("identity") == [S.STUDENT_IDENTITY]:
                            page._ykt_student_catalog_count = (None if page._ykt_catalog_failed
                                else len(payload["data"]["list"]))
                    except (Error, ValueError, AttributeError, TypeError):
                        page._ykt_catalog_failed = True
                if (urlsplit(response.url).hostname == urlsplit(page.url).hostname and
                        (path.startswith("/v2/api/web/logs/") or
                         path.startswith("/v2/api/web/classrooms/") or
                         path in tuple(S.REPORT_API_PREFIX + name for name in S.REPORT_API_NAMES) or
                         path == "/api/v3/classroom-report/lesson/basic-info" or
                         path in (S.COURSE_API_PATH, S.ARCHIVE_API_PATH)) and
                        response.status in (401, 403, 429)):
                    page._ykt_access_blocked = True

            page.on("response", access_guard)
            yield context, page
        finally:
            context.close()


def navigate(page, url: str, stop: Event, emit: Callable[[str], None], retries=3):
    page._ykt_access_blocked = False
    page._ykt_catalog_failed = False
    page._ykt_student_catalog_count = None
    # Initial attempt plus at most three timeout retries; no raw Playwright error logs.
    for attempt in range(retries + 1):
        check_stop(stop)
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=15000)
            if response and response.status in (401, 403, 429):
                raise NeedsHuman("页面要求重新授权、限制访问或限流，请人工检查浏览器")
            return
        except TimeoutError:
            if attempt == retries:
                if retries == 0:
                    raise TimeoutError("页面导航超时") from None
                raise PageChanged("页面导航连续超时，已停止本课程") from None
            emit("页面导航超时，正在重试 {}/{}".format(attempt + 1, retries))
            if stop.wait(min(attempt + 1, 3)):
                raise Stopped()


def ensure_login(page, origin: str, stop: Event, emit: Callable[[str], None],
                 timeout_ms=300000):
    navigate(page, origin + S.INDEX_PATH, stop, emit)
    emit("正在验证登录；如显示登录页面，请在浏览器中人工登录")
    try:
        wait_condition(page, S.LOGIN_READY, stop, timeout_ms=timeout_ms)
    except TimeoutError:
        raise NeedsHuman("尚未验证登录，请完成人工登录后重新运行") from None
    if urlsplit(page.url).netloc != urlsplit(origin).netloc:
        raise NeedsHuman("登录跳转至其他站点，请人工核对入口")
    emit("登录页面验证通过")
