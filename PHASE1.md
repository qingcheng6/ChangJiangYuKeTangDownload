# 阶段1验证入口

本文件保留阶段1控制台入口说明。阶段3已加入下载引擎和 GUI 集成，当前使用方法参见 `PHASE3.md`。

本机环境已建立，可双击 `run_stage1.bat` 扫描；也可执行：

```powershell
.venv/Scripts/python.exe main.py
.venv/Scripts/python.exe main.py --login-only
.venv/Scripts/python.exe main.py --cached
```

新机器环境准备（Python 3.9+，64 位）：

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -m playwright install chromium
```

首次人工登录，程序根据真实课程页状态继续；Ctrl+C 安全停止。
内置 Chromium 启动失败时尝试已安装的 Chrome，可用 `--channel chrome` 明确指定。
不同雨课堂域名使用不同本机资料与缓存，其他域名的 DOM 兼容性尚未验证。

输出为 `.local/<雨课堂域名>/courses.json`。结果包含课程、班级、归档标志、
稳定课堂记录 ID、courseware_id、课时名称、原始毫秒时间、分页结束状态和逐课程状态。
`complete` 才表示本次目录中每门课程的日志分页都已结束；其他状态均为部分结果。
课时入口暂用稳定标识，`entry_url` 留空，不编造报告链接。

扫描只读取课程列表、归档目录和课堂日志，不进入每个课时的习题，不修改归档状态。
当前已核对版本的课程列表为一次返回、日志为滚动分页；结构变化会报告异常。
本地资料含登录会话，请勿分享 `.local`；不导出 Cookie/Token，不保存网络响应正文，
不记录浏览器资料目录，不承诺 SessionStorage 跨启动恢复。
`html` 是用户原有快照，只供离线验证，不代表在线授权或扫描成功。

遇到登录/权限/安全验证状态不明确时，暂停自动操作并保留浏览器，
由用户人工处理后回到控制台按回车重扫，或输入 q 结束。保留部分结果，
当前没有后台常驻任务。
