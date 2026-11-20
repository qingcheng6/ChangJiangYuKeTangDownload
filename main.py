"""Console scanner and desktop scanner/downloader entry point."""

import argparse
import signal
import sys
from pathlib import Path
from threading import Event
from urllib.parse import urlsplit

from ykt.browser import NeedsHuman, Stopped, ensure_login, open_browser
from ykt.scanner import scan
from ykt.storage import read_json
from ykt.accounts import Accounts

ROOT = Path(__file__).resolve().parent


def emit(message):
    print(message, flush=True)


def main():
    parser = argparse.ArgumentParser(description="雨课堂教学资源批量导出工具 V2.0")
    parser.add_argument("--origin", default="https://changjiang.yuketang.cn")
    parser.add_argument("--channel", choices=("chrome", "msedge"))
    parser.add_argument("--account", help="本地账号ID；默认使用界面最后选择的账号")
    parser.add_argument("--login-only", action="store_true")
    parser.add_argument("--cached", action="store_true", help="仅查看缓存摘要，不验证登录")
    parser.add_argument("--gui", action="store_true", help="打开桌面界面")
    parser.add_argument("--login-timeout", type=int, default=300, help="人工登录等待秒数")
    args = parser.parse_args()
    parts = urlsplit(args.origin)
    if (parts.scheme != "https" or parts.username or parts.password or parts.query or
            parts.fragment or parts.path not in ("", "/") or
            not parts.hostname or not (parts.hostname == "yuketang.cn" or
                                       parts.hostname.endswith(".yuketang.cn"))):
        parser.error("入口应为雨课堂 HTTPS 域名，不可包含路径、查询或凭证")
    origin = "https://" + parts.netloc
    try:
        accounts = Accounts(ROOT, origin)
    except (ValueError, OSError):
        emit("账号配置无法读取，原文件保留；请检查本地配置或恢复备份")
        return 1
    account = accounts.get(args.account) if args.account else accounts.get()
    if account is None and not args.gui:
        parser.error("请先通过GUI添加或选择本地账号")
    site_dir = accounts.site_dir(account) if account else None
    cache = site_dir / "courses.json" if site_dir else None
    if args.gui:
        if args.cached or args.login_only:
            parser.error("--gui 不与 --cached 或 --login-only 同时使用")
        from ykt.gui import run_gui
        if args.account:
            accounts.activate(args.account)
        run_gui(ROOT, origin, args.channel)
        return 0
    if args.cached:
        try:
            result = read_json(cache)
        except (FileNotFoundError, ValueError, OSError):
            emit("当前账号没有可读课程缓存，请在GUI选择该账号并扫描")
            return 2
        emit("本地缓存（未重新验证）：{}，{} 门课程，{} 个课时".format(
            result["status"], len(result["courses"]),
            sum(len(x["lessons"]) for x in result["courses"])))
        return 0
    stop = Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    profile = site_dir / "browser"
    try:
        with open_browser(profile, emit, args.channel) as (_, page):
            while not stop.is_set():
                try:
                    if args.login_only:
                        ensure_login(page, origin, stop, emit, args.login_timeout * 1000)
                        return 0
                    result = scan(page, origin, cache, stop, emit,
                                  login_timeout_ms=args.login_timeout * 1000,
                                  expected_owner=account.get("owner"))
                    accounts.bind(account["id"], result["owner_fingerprint"])
                    emit("扫描结果：{}；课程 {}，课时 {}".format(
                        result["status"], len(result["courses"]),
                        sum(len(x["lessons"]) for x in result["courses"])))
                    return 0 if result["status"] == "complete" else 2
                except NeedsHuman as exc:
                    emit("已暂停自动操作：" + str(exc))
                    if page.is_closed():
                        return 3
                    emit("浏览器保留供人工处理。处理后回到控制台按回车重试，输入 q 结束。")
                    try:
                        answer = input().strip().lower()
                    except EOFError:
                        return 3
                    if answer == "q":
                        return 3
            return 2
    except NeedsHuman as exc:
        emit("需要人工处理：" + str(exc))
        emit("已暂停自动操作。保留已扫描结果；处理后重新运行即可重扫。")
        return 3
    except Stopped:
        emit("已停止")
        return 2
    except Exception as exc:
        # Do not print tracebacks/Playwright exception bodies, profile paths or URLs.
        emit("操作失败（{}），请检查浏览器页面和本地环境".format(type(exc).__name__))
        return 1


if __name__ == "__main__":
    sys.exit(main())
