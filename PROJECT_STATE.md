# 雨课堂习题图片下载工具：项目状态

更新时间：2026-10-29（Asia/Shanghai）。阶段1至4已完成并停止。历史阶段数据保持原记录，当前扫描为63课程班级/337课时；验证范围与限制见阶段4记录及TEST_REPORT.md。

## 已完成模块

- `.venv`：本地 Python 环境，`requirements.txt` 固定 Playwright 1.56.0。
- `ykt/browser.py`：同步 Playwright persistent context、人工登录状态验证、串行导航、超时重试、停止事件、异常信息脱敏。
- `ykt/selectors.py`：真实 DOM 定位与只读前端状态结构集中管理；字段发生变化时明确报错。
- `ykt/scanner.py`：我听的课、归档课程目录、课程课堂日志滚动分页、稳定标识、逐课程失败与部分结果保存。
- `ykt/storage.py`：UTF-8 JSON、临时文件、fsync、原子替换。
- `main.py` / `run_stage1.bat`：阶段1控制台入口、手动登录、缓存摘要、Ctrl+C；需要人工处理时保留浏览器，回车重扫或 q 退出。
- `PHASE1.md`：当前阶段使用方法和边界。
- `tests/test_phase1.py`：真实快照 DOM 回归、Python 3.9 语法、标识验证、停止事件。
- `ykt/gui.py`：ttk.Treeview 二级课程树、自绘三态勾选图标、鼠标与空格切换、全局全选/清空、展开/折叠、目录选择与本机保存、进度条/计数/当前课程课时/滚动日志、缓存与人工处理状态。
- `ykt/selection.py`：按课程班级ID+课堂记录ID选择、父子三态、展示顺序任务列表、刷新保留选择（同账号）、空课程不可产生任务。
- `ykt/worker.py`：单独同步 Playwright 工作线程、Queue 深拷贝事件、停止与人工继续事件、退出时关闭上下文；不引用任何 Tk 控件。
- `main.py --gui` / `run_stage2.bat`：阶段2界面入口；阶段1控制台入口保留。
- `PHASE2.md`、`tests/test_phase2.py`、`tools/verify_phase2_live.py`：界面说明、真实缓存/Tk测试、可选真实窗口观察入口。
- `ykt/extractor.py`：正常课时报告、平台原生报告frame、只读报告响应与模型/DOM完整性核对、习题筛选、重复放映事件去重、图片资源候选提取。
- `ykt/files.py`：Pillow实际格式/完整性验证、Windows文件名与UTF-16路径预算、重名分配、目录边界校验、账号范围JSON任务清单、OS独占锁、大小/SHA-256恢复验证。
- `ykt/downloader.py`：授权context.request串行请求、图像验证、最多2次图片重试、临时文件原子替换、同资源/同内容去重、损坏重下、逐课时失败记录与安全停止。
- `ykt/worker.py` / `ykt/gui.py`：已接入真实下载按钮、固定任务快照、逐课时计数与图片累计进度、人工暂停/继续、下载线程停止/退出。界面标题为阶段3。
- `run_stage3.bat` / `PHASE3.md` / `tools/verify_phase3*.py` / `tests/test_phase3.py`：阶段3入口、文档、真实样例验证与回归测试。
- 新增依赖 Pillow==11.3.0（Python >=3.9，有当前Python3.14 Windows wheel），用于内容格式检测与可靠解码；未使用图片转换伪造下载结果。
- 阶段4已新增正式 `run.bat` / `bootstrap.py`、`README.md`、`TEST_REPORT.md`、`ykt/recovery.py` 与基础交付回归；具体结果见文末阶段4记录。

## 真实页面依据与关键定位

用户原有 `html/雨课堂.html`、`雨课堂1.html`、`雨课堂2.html` 保留不改。
2026-10-28 经用户在独立窗口人工登录长江雨课堂后在线核对：

| 页面/用途 | 已验证结构 |
| --- | --- |
| 入口 | `https://changjiang.yuketang.cn/v2/web/index` |
| 登录后的我听的课 | `role=tab`、精确名称 `我听的课`；`#tab-student`、`.index__view` |
| 普通课程 | `#pane-student .lesson-cardS`；`h1`、`.className`、`.teacherName` |
| 课程只读数据 | `.index__view.__vue__` 为 `IndexView`；`originalTableData2`、`tab2Request`、`isLoading`、`user_id` |
| 目录响应 | 实际页面触发 `/v2/api/web/courses/list?identity=2`（学生），`errcode=0`，`data.list`；导航前安装被动监听，以实际响应条数核对模型和DOM，不自行构造请求 |
| 归档入口 | 精确文本 `我的归档`，`.archiveDialog`，内部 `role=tab` 名称含 `我听的课` |
| 归档列表 | 页面实际触发 `/v2/api/web/classroom_archive`；`errcode=0`、`data.classrooms`；`.archiveCardS` |
| 归档只读元数据 | `id`、`course.name`、`name`、`teacher.name`、`type_count` 中 `type=14` 的课堂统计 |
| 课程入口 | 正常点击普通课程卡片得到 `/v2/web/studentLog/{classroom_id}`；另验证归档 ID 25393947 可直接访问同一路由，无须移出归档 |
| 学习日志 | `.studentLog__view`、`#pane-log .logs-list:visible`、`.studentCard`、`.date-box`、`.activity-box`、`.time`、`.activity-info h2` |
| 课堂类型 | 图标 `use[*\|href="#icon-ketang"]`；`StudentLogView.sourceData` 中 `type=14` |
| 稳定课时标识 | 当前课程 `classroomId` + 记录 `id`、字符串 `courseware_id`；另存 `title`、`create_time` |
| 日志加载完成 | `StudentLogView.loaded=true`、`isLoading=false`、`hasMore=false`；验证 `classroomId` 与目标一致 |
| 滚动分页 | `.viewContainer` 是实际滚动容器；正常滚动触发页面自身加载逻辑，观察 `page`、`hasMore` 和记录数量 |

只读取上述白名单字段，不调用 Vue 内部方法、不导出完整组件状态、不保存网络响应。
这依赖当前网站暴露的 Vue 2 结构；未来版本变化需重新核对，不能假装兼容。

## 扫描结果与缓存

- 首次真实扫描：普通课程班级 38 + 归档课程班级 25 = 63，课堂记录 335；63 个课程日志均到 `hasMore=false`，失败 0。
- “课程”以课程班级 ID 为单位，同名不同班级不合并；部分课程只有试卷/公告，没有课堂记录，返回 0 是真实结果。
- 没有进入每个课时的习题，也没有下载课件、提交习题、答题或更改归档。
- `.local/changjiang.yuketang.cn/courses.json`：结构化完整/部分扫描缓存，以 `source=live_browser`、整体和逐课程 `status` 明确标注。
- 课时保留稳定 ID；`entry_url=null`、`entry_kind=classroom_log_record`，尚不承诺报告链接或习题入口。
- `.local/changjiang.yuketang.cn/verification.json`：独立只读抽查的验证摘要。
- `.local` 及用户快照已加入 `.gitignore`。会话仅存本机，程序不记录资料目录或 Cookie/Token/密码；不承诺 SessionStorage 跨启动保持。

## 已执行验证

- 环境：Windows 11 build 26200，Python 3.14.7，Playwright 1.56.0，安装的 Chrome 156.0.8078.48。
- 真实登录：首次人工扫码完成，页面状态验证通过。
- 会话恢复：关闭 context 后重新启动，`main.py --channel chrome --login-only --login-timeout 30` 无须再次扫码，通过；默认启动回退 Chrome 的恢复也通过。
- 首次完整在线扫描通过，63 门、335 条、失败 0；本地缓存结构、唯一 ID、分页结束状态均核验。
- 归档课堂计数：25 门的 `type_count[type=14].count` 全部与缓存课时数一致。
- 二次抽查：重新进入普通物理学 A2，滚动加载得到 25 条；记录 ID、名称、顺序与可见 DOM 及缓存一致。
- 多页混合日志：普通化学 B 和高等数学 A2 实际加载到第3页；只收录课堂，后者为试卷记录而无课堂，不误计为课时。
- 真实快照回归 5 项通过；隐藏日志分类面板中的重复内容被排除。
- `pip check` 通过；Python 3.9 的 `pip --dry-run --python-version 3.9 --only-binary=:all:` 解析成功（greenlet 3.2.4）；代码按 Python 3.9 语法解析通过。
- 最终默认入口 `main.py` 全量在线回归退出码0：自动回退 Chrome、恢复会话、扫描63个课程班级、335条课堂记录、失败0，全部课程分页结束；缓存已核验。
- 真实安全停止验证：在工程经济学加载下一页前设置停止事件，`stop_probe.json` 为 `stopped`，保留20条已读记录，当前课程 `incomplete`，剩余62门 `pending`；完整 `courses.json` 未被测试覆盖。
- `verification.json` 已补记最终 CLI 和安全停止验证结果。浏览器与测试进程均已关闭，不留下后台自动操作。

## 已修复问题及实际差异

- 模型返回后卡片 DOM 尚未渲染：改为等待已验证目录响应，并核对模型与卡片数量后继续。
- 同一日志在多个隐藏分类面板重复：使用 `:visible` 进行 DOM 核验；引擎使用稳定记录 ID 去重。
- 首屏显示20条不代表结束：滚动读取分页，明确等待 `hasMore=false`。
- 当前课程目录一次返回全部项目，没有发现课程目录分页控件；只验证了当前站点版本，不声称任意未来分页/虚拟列表已支持。
- Windows 本机安装的 Playwright 内置 Chromium 141 无法启动（SideBySide 激活上下文错误）；headless shell 可用于快照测试。程序自动回退已安装 Chrome，已验证；没有修改系统安全设置或篡改浏览器安装文件。
- 默认 CLI 首次全量回归在水土保持学未于30秒内达到加载状态，保留 `needs_human` 部分结果并暂停。单独重新访问该已授权课程后页面正常；尚未确定该次超时根因。补充匹配课程日志页的最多3次加载重试，以及已验证目录/日志接口的401/403/429被动拦截，后者直接交人工处理。最终回归结果见上方测试记录。
- 网站自身存在原生 iframe（用户课时报告快照所示）；本项目未创建 iframe 或嵌套方案。习题内容的后续访问方式留待阶段3真实检查。

## 阶段2验证及局部修复

- 使用真实63课程/335课时缓存进行三态、父子选择、全选/清空、同名班级区分、快照隔离、主线程约束测试。最终共13项测试全部通过，包含刷新保留、900×620最小窗口状态栏/树区域可见性和展开/折叠。
- 使用 Windows 原生窗口实点验证：单课时选择→父节点部分选中、课程全选20条、全局335条全选、清空；空格可取消/选中焦点课时。
- 原生 Windows 文件夹对话框实际选择项目目录，并已验证重开窗口恢复该目录。仅创建目录设置，没有创建习题图片目录。
- 修复自绘方框点击未显式聚焦 Treeview 的问题；点击方框后按空格已真实验证有效。
- 修复150%缩放时底部状态栏受 pack 布局挤压：外层改为 grid，将剩余高度分配给树区域，状态栏可见。
- GUI内实际启动浏览器扫描；停止时完成7门、保留53条课堂记录，缓存 `stopped`；工作线程退出，按钮恢复。摘要 `.local/phase2_stop_verification.json`。
- 扫描运行中 Alt+F4 实测安全关闭：停止并保存部分结果，窗口最终退出，工作线程不再存活。摘要 `.local/phase2_close_verification.json`。
- 最终全量GUI回归曾在目录阶段超时，显示错误并恢复控件、保留原缓存，不标为成功。记录 `.local/phase2_catalog_timeout_verification.json`。
- 目录超时定位过程保留：只等待未来响应、只依赖加载标志、将 RAF 条件轮询改为定时条件轮询，均未单独解决本次超时；不能将其描述为已验证根因。
- 最终捕获的真实数据瞬态：学生目录成功响应38条，DOM已有卡片，但 `originalTableData2` 仍是0。先前过早读取该数组，再用0等待DOM最终数量，会在实际渲染38条时一直超时。已改为导航前被动监听实际 `identity=2` 成功响应，得到可信期望条数后，再等待模型和DOM均匹配，最后读取数据；可正确处理真实0课程。独立实际目录读取38+25已通过，最终GUI扫描已继续超过原失败点。
- `wait_condition` 仍按真实条件、100ms间隔检查，避免绑定 RAF 帧；不以经过固定时间作为加载成功。目录响应的状态/errcode/结构仍被核对，401/403/429直接交人工处理。
- 扫描引擎新增可选 `on_progress`（不改变CLI默认用法），GUI接收的每条事件均是独立深拷贝；不解析中文日志作为进度。
- 最终修复后GUI真实全量扫描通过：63课程班级、335课时；任务总数63、完成63、成功63、失败0；缓存整体 `complete`，每门课程日志分页结束。GUI前台时后台浏览器继续扫描，主线程定时观察334次以上；UI与浏览器线程ID不同，Tk回调错误0。
- 最终重扫保留预选的1个真实课时，其父课程保持部分选中；没有重复生成课时。
- `.local/phase2_complete_verification.json` 保存最终全量、线程、勾选、关闭与13项测试的验证摘要；正常启动不生成此观察摘要。
- `run_stage2.bat` 使用Windows CRLF；实际通过批处理启动界面、加载63/335缓存与已保存目录，关闭后退出码0。最初LF版本的启动检查未成功，未计为通过。
- 完成后验证窗口及普通入口窗口均已关闭；浏览器上下文和工作线程已退出。没有进入阶段3，没有下载任何习题图片。

## 阶段3真实页面、实现和验证（2026-10-29）

- 已沿工程经济学真实课堂日志点击进入报告，验证正常路由：`/v2/web/student-lesson-report/{classroom_id}/{courseware_id}/{activity_id}`。后续用扫描所得同一套稳定ID进入该正常报告，报告与资源均由平台原鉴权处理。
- 平台报告自带 `iframe.lesson-report-mobile`，加载同站点`/m/v2/lesson/student/{courseware_id}/overview`。没有创建、嵌入或搭建iframe，不通过直接移动端地址绕权限。
- 实际frame结构：`.courseware-cmp-wrap`；`.tab-wrap`精确文本“习题”；`.slides-list .slide-item`内`.slide-img`是图片区域；`.slide-exercise`是习题记录标记。普通课件、头像、报告统计图不在提取范围。
- 只读组成式状态来自`__vue__._setupState`：`lessonSummaryInfo`、`lessonTimelineSlides`、`showSlides`、`lessonSelectTab`、`isSentProblem`、`lessonStats.problemStatistics.hasProblem`。不调用页面内部业务方法，不答题、不提交、不改收藏或不懂标记。
- 在导航前被动监听`/api/v3/classroom-report/student/{lesson-info,review,detail}?lesson_id=...`，HTTP200且`code=0`才作为已验证数据；核对课时ID、班级ID、review条数、模型与DOM。`review.data.timelineList`无分页字段且当前样例一次返回完整65条；没有猜测分页按钮。
- 真实差异：65条放映事件中24条带“已发送习题”标记，但同一页会重复放映；按`hasProblem && sendProblem`及稳定页ID去重，实际14张，与页面“习题”筛选ID集合一致。初版直接用事件条数核对，曾安全超时、没有下载文件；修复后才保存14张。
- 工程经济学样例筛选页码顺序为P39、40、42、43、44、45、47、48、49、50、51、52、53、54；首次实际下载14张JPEG。抽检首张为1280×960、217096字节，视觉为完整习题页；列表提供URL与大图预览来源一致，没有推测更高分辨率URL。
- 数学规划样例41条展示事件，无已发送课堂习题，“习题”标签隐藏；普通物理学A2另一次只读检查为10条、无习题。数学规划下载任务实际返回`no_images`，没有创建该课程/课时目录。
- 页面/接口登录、权限、限流状态交人工处理；图片HTTP401/403/429、非成功报告业务状态、HTML资源及不可点击筛选均暂停，不绕安全控制。真实安全挑战未人为触发，不声称已端到端验收。
- 修复阶段2潜在竞态：离开首页时旧目录请求被取消导致目录错误标志，不能污染报告等待；目录标志现在只影响目录加载条件，权限标志仍覆盖对应接口。
- 报告导航+加载共用最多3次超时重试；图片首次请求+最多2次重试；请求串行并限速。响应body用Pillow完整解码/格式验证后，原始字节写`.part`、fsync、原子替换。
- 按实际内容识别JPEG/PNG/GIF/WebP/BMP/TIFF/ICO/AVIF后缀；在线下载只验证过本次JPEG。PNG通过真实快照资产内容检测单测；其余格式、srcset/data-src/原图属性、CSS背景、data/blob分支未在线验收。Canvas/内联SVG明确记录不可可靠导出，不用截图冒充原图。
- Windows非法字符、保留名、重名、UTF-16长度预算均已实现；输出路径目标不超过240单位，根目录过长要求换短目录；清单路径必须落在目标根下。使用OS文件锁防止同目录并发写入，进程退出自动释放锁。
- 账号范围任务清单保存在`<目录>/雨课堂习题下载/任务清单_<账号摘要>.json`，不保存资源签名URL、Cookie、Token或密码。只存资源摘要、稳定ID、相对路径、大小、SHA-256、完成/失败状态及原因。实际检查清单资源记录没有HTTP地址或auth_key。
- 重启恢复：新进程再次处理相同课时，14张全部通过本地校验并跳过，下载0张；摘要`.local/phase3_restart_skip_verified.json`。
- 损坏恢复：仅截断本项目测试目录中的首张实际下载图并保留备份；下一进程仅重下1张、跳过13张，恢复字节与原图一致，其他13张mtime未变。摘要`.local/phase3_corruption_recovery_verified.json`。
- 安全停止：实际保存首张后设置停止事件，保留1张完整文件且无`.part`残留；新进程重跑跳过1张、补齐13张。摘要`.local/phase3_stop_verified.json`、`phase3_stop_resume_verified.json`。
- 失败重试：在专用测试目录制造真实本地临时文件名冲突，没有模拟成功资源；首张尝试3次后标失败，其余13张继续保存。清除本项目创建的空冲突目录后，下一进程仅补下1张、跳过13张。未伪称该测试为真实网络/平台限流测试。摘要`.local/phase3_retry_failure_verified.json`、`phase3_retry_recovery_verified.json`。
- GUI：实际点击“开始下载”；保存1张后经主线程停止控件通路安全停止；再次点击同一下载按钮，验证原图跳过+余下补齐。任务总数2、完成2、成功2、失败0，累计补下13张、跳过1张，另有无图片课时1个。UI与下载线程ID不同，Tk回调错误0，观察循环持续运行。摘要`.local/phase3_gui_complete_verified.json`与`phase3_gui_stop_verified.json`。
- 测试：阶段1/2回归及新增文件完整性、原子保存、锁与目录边界、Windows名称、真实习题快照范围等，共19项全部通过。`pip check`通过；Python3.9依赖dry-run解析到Pillow11.3.0、Playwright1.56.0、greenlet3.2.4，3.9语法检查通过；没有把这些描述为3.9实机通过。
- 实际下载样例保留在`.local/phase3_output`、`phase3_stop_output`、`phase3_retry_output`、`phase3_gui_output`中；每组完成后均是14张习题图，没有下载数学规划普通课件。正常用户运行不会生成这些验证摘要。
- `run_stage3.bat`已按Windows CRLF保存，依赖已安装时跳过pip安装；实际批处理启动新版GUI、读取63/335缓存及恢复原保存目录，关闭后退出码0。
- GUI验证退出后恢复了用户先前选择的保存目录；观察窗口、正常入口窗口、下载浏览器上下文和工作线程均已关闭。未执行阶段4。
- `.local/phase3_complete_verification.json`汇总真实下载、重启、损坏、停止、失败重试、GUI与启动入口的验证摘要。没有声称账号全部335课时下载均通过。

## 阶段3结束时的后续与未验证范围（阶段4结果见下方）

- Windows 10、Python 3.9 实机运行尚未验证，不能将依赖解析/语法检查描述为实机通过。
- 未人为触发验证码、429、权限变更或 Cookie 过期；暂停与错误路径尚未在这些真实场景验收。
- 其他雨课堂域名的 DOM 兼容性未验证；会话与缓存按域名隔离。
- 阶段2的“人工处理完成，继续”事件通路已实现；未人为触发真实验证码/权限过期来验证该操作，不能宣称此场景端到端已通过。
- 阶段3已实现并完成上述限定真实样例验证；不能声称账号335个课时全量下载通过，其他报告版本/课程需阶段4扩大验收。
- 待阶段4：完整端到端与异常验收、正式 run.bat、README 和交付检查。

恢复上下文时先读取此文件及相关模块，局部修改；以下阶段4已由用户“继续”授权执行。

## 阶段4集成验收与交付（2026-10-29）

- 新增正式 `run.bat`（Windows CRLF）及标准库 `bootstrap.py`，首次创建项目 `.venv`、安装固定依赖并检查浏览器；已有环境直接启动。Tk/Playwright仍只在实际界面/工作线程内使用。
- 新增 `README.md`、`TEST_REPORT.md`，写明操作、恢复、安装排错、实际测试与未验证边界；旧 `PHASE*.md` 保留为历史。
- GUI去掉阶段标记，新增“失败 / 未完成…”窗口及“仅勾选列表课时”；`ykt/recovery.py`只读清单，不把历史完成状态当作本地文件完整性验证。
- `Manifest.read_existing()`增加嵌套结构、资源记录、路径边界验证，损坏清单保留；`read_json`拒绝非对象顶层。原19项回归继续通过，新增6项无私人素材基础测试，共25项通过；`pip check`通过。
- 最新真实全量GUI扫描63班级、337课堂，成功63/63、失败0。相比历史335新增2条进行中课堂，并非数据伪造或去重错误。
- 第一轮混合下载选择7课时，实际6成功、1失败、保存26张；失败为数学规划正在进行的课堂，正常报告无frame，超时记录保留 `.local/phase4_first_e2e_verification.json`。未将其算作无图片。
- 根据真实日志 `is_finished` 字段增补缓存完成状态（`includes_lesson_completion=True`）和树中“进行中”标记；明确进行中报告不可用原因，不进入实时课堂。独立在线复核1课时失败、下载0、报告请求0，证据 `.local/phase4_ongoing_verified.json`。
- 第二轮真实扫描后，从5班级选择7个已结束课时：成功7、失败0，其中4课时含26张JPEG、3课时无图；26张全部大小/SHA256校验跳过。UI/工作线程不同、Tk回调异常0。证据 `.local/phase4_e2e_verification.json`，第一轮失败历史不被抹除。
- 将日志滚动脚本的RAF等待改为同步滚动/事件，避免后台页RAF挂起；化学真实3页、17条ID顺序与新缓存一致、hasMore=false，证据 `.local/phase4_paging_verified.json`。
- 原图cover仅在该页没有任何候选资源且是唯一图片时作为回退，避免子图片失败后用整页封面冒充；习题区域和原图来源仍由真实DOM核对。
- 浏览器关闭故障测试首次在Playwright请求回调直接关闭context出现同步重入，未计通过；改为实际报告核验完成后的应用回调关闭。已确认 `needs_human`、课时stopped及明确原因落盘、无图片文件，证据 `.local/phase4_browser_close_verified.json`。
- 用上述真实未完成任务打开恢复窗口，150%缩放发现底部按钮被pack挤掉；改grid后重新原生点击“仅勾选列表课时”→选中1→点击开始，实际保存14张、成功1/1、未完成0、回调异常0，关闭后工作线程退出；证据 `.local/phase4_recovery_gui_verified.json`。未模拟网络成功。
- 正式 `run.bat` 在已有环境实测恢复63/337缓存和原保存目录，正常关闭退出码0。交付ZIP解压至 `.local/release_smoke_d4e65372`，原无虚拟环境/账号缓存，实际创建venv、安装依赖、启动空缓存GUI，正常退出0；解压环境6项基础测试通过。浏览器缓存复用本机已有安装，不声称全新系统浏览器下载安装通过。
- `tools/package_release.py`仅白名单打包19个源码/文档/基础测试文件到 `dist/yuketang_exercise_downloader.zip`，核验ZIP CRC和条目集合，附 `.sha256`。不含`.local`、`.venv`、HTML、课程缓存或下载图片；无外部发布或上传。
- 所有验收GUI/浏览器/线程已退出；原保存目录设置恢复。测试样例和私有证据仅留在本机`.local`，正常用户启动不生成观察探针。

## 最终保留的限制

- 实机为Windows11/Python3.14.7；Windows10、Python3.9实机未验收，3.9仅语法和依赖解析通过。
- 账号337课堂未全部逐一下载；混合验收仅上述7个已结束课时，以及单独恢复/故障样例。
- 真实验证码、429、权限变更、Cookie过期的人工处理流程未人为触发验收；代码中遇到这些状态暂停。
- 当前站点版本和已观察的课程目录响应/日志分页/习题报告已验证；其他域名、未来DOM或新的分页形式未验证。
- 在线图片样例为JPEG；其他格式、srcset/data-src/CSS/data/blob分支未逐一在线验证；canvas/内联SVG不可可靠提取则记录原因。
- 本机内置Chromium SideBySide错误仍存在，已验证Chrome自动回退；未修改系统环境冒充修好Chromium。

四阶段工作到此结束。后续收到新问题时以当前模块局部修复，先读取本文件，不自行重复全量下载或扩大访问范围。
