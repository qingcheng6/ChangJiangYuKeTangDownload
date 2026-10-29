"""Read currently accessible course lists and classroom log metadata only.

The site's Vue 2 view models supply stable IDs and explicit lazy-load state.
Only verified, allowlisted fields are read; no internal methods are called.
"""

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from typing import Callable
from urllib.parse import urlsplit

from playwright.sync_api import Error, TimeoutError

from . import selectors as S
from .browser import (NeedsHuman, PageChanged, Stopped, check_stop, ensure_login,
                      navigate, wait_condition)
from .storage import write_json


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def valid_id(value):
    value = str(value)
    if not value.isdigit() or int(value) <= 0:
        raise PageChanged("页面标识格式发生变化，需要重新核对")
    return value


def course_catalog(page, stop: Event):
    # The index may already be on the student tab and loading automatically.
    # Waiting only for a *future* response can miss that in-flight request.
    # Use the verified loaded model, with response error guards installed before
    # navigation, then independently wait for its matching DOM rendering.
    page.get_by_role("tab", name=S.STUDENT_TAB_NAME, exact=True).click()
    # The observed request is registered by open_browser *before* navigation.
    # A temporary empty model is not a successful empty catalog. Use the actual
    # student response count, including zero, before reading its rendered model.
    import time
    deadline = time.monotonic() + 30
    while getattr(page, "_ykt_student_catalog_count", None) is None:
        check_stop(stop)
        wait_condition(page, "() => true", stop, timeout_ms=1000)
        if time.monotonic() >= deadline:
            raise TimeoutError("课程目录响应等待超时")
        if stop.wait(0.1):
            raise Stopped()
    wait_condition(page, S.INDEX_READY, stop)
    wait_condition(page, S.COURSE_RENDERED, stop, arg=page._ykt_student_catalog_count)
    data = page.locator(S.INDEX_VIEW).evaluate(S.INDEX_DATA)
    wait_condition(page, S.COURSE_RENDERED, stop, arg=len(data["courses"]))
    valid_id(data["account"])
    cards = page.locator(S.COURSE_PANEL).locator(S.COURSE_CARD)
    # Current live version returns the full course list in one response.
    # Do not silently truncate if a future version starts virtualizing/paginating.
    if cards.count() != len(data["courses"]):
        raise PageChanged("课程模型与页面卡片数量不一致，不能确认课程列表完整")
    for course in data["courses"]:
        valid_id(course["id"])
    return data


def archived_catalog(page, stop: Event):
    check_stop(stop)
    with page.expect_response(
            lambda r: urlsplit(r.url).path == S.ARCHIVE_API_PATH,
            timeout=30000) as pending:
        page.get_by_text("我的归档", exact=True).first.click()
    response = pending.value
    if response.status in (401, 403, 429):
        raise NeedsHuman("归档课程访问需要人工处理")
    if response.status != 200:
        raise PageChanged("归档课程列表请求失败")
    payload = response.json()
    if payload.get("errcode") != 0:
        raise PageChanged("归档列表未返回成功结果")
    rows = payload.get("data", {}).get("classrooms")
    if not isinstance(rows, list):
        raise PageChanged("归档列表结构变化")
    dialog = page.locator(S.ARCHIVE_DIALOG)
    dialog.get_by_role("tab", name="我听的课").click()
    courses = []
    for row in rows:
        counts = row.get("type_count")
        if not isinstance(counts, list):
            raise PageChanged("归档课堂计数结构变化")
        expected = next((item["count"] for item in counts if item["type"] == 14), 0)
        courses.append(dict(id=valid_id(row["id"]), name=row["course"]["name"],
                            class_name=row["name"],
                            teacher=row.get("teacher", {}).get("name", ""),
                            expected_lesson_count=expected,
                            archived=True))
    if dialog.locator(S.ARCHIVE_CARD).count() != len(courses):
        raise PageChanged("归档模型与页面数量不一致")
    dialog.get_by_text("取消", exact=True).click()
    return courses


def scan_lessons(page, course, origin: str, stop: Event, emit: Callable[[str], None]):
    for attempt in range(4):
        navigate(page, origin + S.COURSE_PATH.format(classroom_id=course["id"]), stop, emit)
        try:
            wait_condition(page, S.LOG_READY, stop, arg=course["id"])
            break
        except TimeoutError:
            # Only retry a matching, already authorized log view. Missing views,
            # login redirects and access responses require a person immediately.
            matching = page.locator(S.LOG_VIEW).count() == 1 and page.locator(
                S.LOG_VIEW).evaluate(
                    "(e,id)=>String(e.__vue__?.classroomId)===id", course["id"])
            if not matching or attempt == 3:
                raise NeedsHuman("课程页未达到已验证状态；请检查登录、权限或安全验证") from None
            emit("课程日志加载超时，重新加载 {}/3".format(attempt + 1))
            if stop.wait(attempt + 1):
                raise Stopped()
    entry_path = page.evaluate("location.pathname")
    expected = S.COURSE_PATH.format(classroom_id=course["id"])
    if entry_path != expected:
        raise NeedsHuman("课程入口发生跳转，需要人工核对")
    course["entry_url"] = origin + entry_path
    seen = {}
    pages = []
    for _ in range(1000):  # Fail explicitly on safety bound; never claim exhaustion.
        check_stop(stop)
        state = page.locator(S.LOG_VIEW).evaluate(S.LOG_DATA)
        if state["classroom_id"] != course["id"]:
            raise PageChanged("课程页面标识不匹配")
        pages.append(state["page"])
        for row in state["lessons"]:
            valid_id(row["id"])
            valid_id(row["courseware_id"])
            key = row["id"]
            row["entry_url"] = None
            row["entry_kind"] = "classroom_log_record"
            if key in seen and seen[key] != row:
                raise PageChanged("同一课堂记录出现冲突")
            seen[key] = row
        course["lessons"] = list(seen.values())
        if not state["has_more"]:
            if ("expected_lesson_count" in course and
                    len(seen) != course["expected_lesson_count"]):
                raise PageChanged("课堂记录数量与归档统计不一致，需要重新核对")
            course["pagination"] = dict(pages=pages, has_more=False)
            return
        emit("继续加载课堂日志，第 {} 页".format(state["page"] + 1))
        if stop.wait(0.8):  # Intentional serial request pacing, not a readiness wait.
            raise Stopped()
        # Initial attempt plus two retries for an unchanged lazy-load state.
        for attempt in range(3):
            previous_count = page.locator(S.LOG_VIEW).evaluate(
                "e=>e.__vue__.sourceData.length")
            page.locator(S.SCROLLER).evaluate(S.SCROLL_END)
            try:
                wait_condition(page, S.LOG_ADVANCED, stop,
                               arg={"page": state["page"], "count": previous_count})
                break
            except TimeoutError:
                if attempt == 2:
                    raise PageChanged("滚动分页未完成，已保留部分课时，需重扫") from None
                emit("滚动加载未完成，重试 {}/2".format(attempt + 1))
    raise PageChanged("课堂日志页数超过安全上限，结果不完整")


def scan(page, origin: str, cache: Path, stop: Event, emit: Callable[[str], None],
         login_timeout_ms=300000, on_progress=None, expected_owner=None):
    ensure_login(page, origin, stop, emit, timeout_ms=login_timeout_ms)
    emit("正在读取“我听的课”目录")
    catalog = course_catalog(page, stop)
    actual_owner = hashlib.sha256((origin + ":" + catalog["account"]).encode()).hexdigest()
    if expected_owner is not None and actual_owner != expected_owner:
        raise NeedsHuman("该本地账号资料中登录了其他账号，请切回原账号或新增独立账号；旧缓存未改动")
    regular_count = len(catalog["courses"])
    emit("正在读取归档课程目录")
    catalog["courses"].extend(archived_catalog(page, stop))
    result = dict(schema_version=1, source="live_browser", origin=origin,
                  owner_fingerprint=hashlib.sha256(
                      (origin + ":" + catalog["account"]).encode()).hexdigest(),
                  started_at=utc_now(), updated_at=utc_now(), status="running",
                  course_list_verified=True, includes_lesson_completion=True, regular_courses=regular_count,
                  archived_courses=len(catalog["courses"]) - regular_count,
                  courses=[], errors=[])
    unique = set()
    for item in catalog["courses"]:
        if item["id"] in unique:
            continue
        unique.add(item["id"])
        result["courses"].append(dict(item, status="pending", lessons=[]))
    emit("课程目录：{} 门普通课程，{} 门归档课程".format(
        result["regular_courses"], result["archived_courses"]))

    def save():
        result["updated_at"] = utc_now()
        write_json(cache, result)

    def report(current_course="—"):
        if on_progress is not None:
            statuses = [item["status"] for item in result["courses"]]
            success = statuses.count("complete")
            failed = statuses.count("failed")
            on_progress(dict(total=len(statuses), completed=success + failed,
                             success=success, failed=failed,
                             current_course=current_course, result=result))

    save()
    report()
    try:
        for index, course in enumerate(result["courses"], 1):
            check_stop(stop)
            emit("扫描课程 {}/{}：{}".format(index, len(result["courses"]),
                                           " ".join(course["name"].split())))
            course["status"] = "scanning"
            report(course["name"])
            try:
                scan_lessons(page, course, origin, stop, emit)
                course["status"] = "complete"
                emit("已核对 {} 个课时，日志分页结束".format(len(course["lessons"])))
            except (NeedsHuman, Stopped):
                course["status"] = "incomplete"
                raise
            except (PageChanged, TimeoutError, Error, KeyError, TypeError, ValueError) as exc:
                if page.is_closed():
                    course["status"] = "incomplete"
                    raise NeedsHuman("浏览器已关闭，请重新启动") from None
                course["status"] = "failed"
                # Fixed reason labels only: raw browser errors may contain URLs/secrets.
                reason = str(exc) if isinstance(exc, PageChanged) else "页面结构或加载异常"
                course["error"] = reason
                result["errors"].append(dict(course_id=course["id"], reason=reason))
                emit("本课程扫描失败：{}；继续下一门".format(reason))
            save()
            report(course["name"])
            if stop.wait(0.8):
                raise Stopped()
        result["status"] = "complete" if not result["errors"] else "partial"
    except Stopped:
        result["status"] = "stopped"
        emit("已停止，保留本地部分结果")
    except NeedsHuman:
        result["status"] = "needs_human"
        raise
    finally:
        save()
        report()
    return result
