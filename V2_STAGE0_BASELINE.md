# V2 阶段0：V1.0 兼容性基线

日期：2026-10-29。仅完成检查、备份、基线验证及后续兼容边界记录；未实现多账号、PDF、课件导出，未修改业务模块、选择器、启动器或依赖。

## 回退与备份

- 项目原先没有 Git 仓库。本轮建立本地仓库，V1 源码提交 `d9fb71a`，标签 `v1.0-before-v2`；没有配置远程仓库或上传数据。
- 改动前备份位于 `.local/v2_stage0/20261029_133012/`：`source.zip` 保存38个源码/文档/配置文件，`private_local_backup.zip` 保存1496个本地文件，包括旧浏览器会话、GUI设置、课程缓存、历史任务清单及本地验证记录。`backup_index.json` 记录逐文件SHA-256；两个ZIP均做CRC及逐条SHA-256复核。
- 私人备份含会话数据，只保存在本机，受现有 `.gitignore` 排除，不进入源码提交或交付包。浏览器会话路径不写入运行日志；备份索引也不在聊天中展开。
- 图片不迁移、不覆盖、不删除。基线抽查输出位于上述目录的 `probe_output`，与V1历史目录分离。回退代码与恢复私人数据是两件事：需要时先关闭工具及其浏览器，从源码标签取回指定文件；只在明确需要恢复时手工恢复对应备份，不用清空目录或强制重置替代恢复。

## 现有架构及公开调用边界

| 模块 | 已检查的实际职责及后续复用点 |
| --- | --- |
| `main.py`、`bootstrap.py`、`run.bat` | CLI扫描/缓存摘要/GUI；本地venv、固定依赖、浏览器检查；保持现有一键入口 |
| `browser.py` | `open_browser(profile, emit, channel=None)`使用同步persistent context；调用线程独占context，finally关闭；内置Chromium失败回退Chrome；`ensure_login`核对实际DOM，不保存密码 |
| `scanner.py` | `course_catalog`、`archived_catalog`、`scan_lessons`及`scan`；账号身份由页面模型得到，再计算摘要；按课程串行、日志滚动分页、原子保存部分结果 |
| `selectors.py` | 集中管理真实页面定位与只读Vue状态；无新增或猜测选择器 |
| `selection.py` | `(course_id, lesson_id)`三态选择；更换owner时清理选择；`tasks()`按扫描展示顺序生成任务 |
| `extractor.py` | `extract_lesson(page, origin, task, stop, emit)`返回有序资源候选、课件页ID/页码及不可导出原因；仅习题筛选区域；未结束课堂明确失败 |
| `downloader.py` | `download(context, page, origin, tasks, directory, owner, stop, emit, on_progress=None)`；核对实际账号；复用授权请求、内容识别、每图最多2次重试、原子保存、完整性恢复、安全停止 |
| `files.py` | `Manifest(directory, owner, origin)`管理schema1清单、OS文件锁、Windows名称/长度/冲突/路径边界；大小+SHA-256验证后才跳过 |
| `gui.py` | `CourseApp(root, project_root, origin=..., channel=None)`；主线程Treeview/事件/保存目录设置；当前没有账号框或导出选项 |
| `worker.py` | `ScanWorker(origin, site_dir, channel=None)`；单工作线程、Queue深拷贝、停止/人工继续Event；`start_download(tasks, directory, owner)`复用下载引擎 |
| `storage.py`、`recovery.py` | schema1原子JSON读写；只读历史未完成任务列表，重新下载仍校验文件 |

调用参数和返回字段属于后续兼容边界，优先保持原默认行为，使用可选参数/外层适配扩展；不复制第二套习题下载逻辑。后续要改业务时，先对照源码标签和本基线测试。

## 登录、配置、缓存及历史格式

- 当前是**按站点隔离的单账号资料目录**；GUI和CLI都从项目 `.local/<域名>` 获取站点数据。没有本地账号注册表、备注名或账号选择逻辑。浏览器的persistent context已有浏览器层资料锁；应用尚无独立账号租约或账号切换协调器。
- `.local/gui_settings.json`：`schema_version=1`、`save_directory`，是全局目录设置。
- 站点 `courses.json`：`schema_version=1`、`origin`、`owner_fingerprint`、状态/时间/错误、课程列表；本地现有完整缓存63班级/337课堂。本阶段未覆盖它，也未把缓存统计当作本次全量在线扫描。
- 课程字段包含 `id/name/class_name/teacher/archived/status/lessons/entry_url/pagination`；课时字段含 `id/courseware_id/name/created_at/is_finished/entry_url/entry_kind`。`entry_url`可能为空，以稳定ID构造已验证报告路由。
- `owner_fingerprint=SHA256(origin + ':' + 平台账号ID)`，与后续需要新增的“本地账号唯一ID”不是同一概念。当前缓存路径仍按站点，单靠此摘要不会获得多账号缓存隔离。
- V1根目录：`所选目录/雨课堂习题下载/课程名称/课时名称/习题_001.<真实格式>`；未在课时下建立“习题图片”子目录。`任务清单_<owner前12位>.json`放输出根，文件中保存完整owner及origin。
- 清单schema1：`courses`映射稳定班级ID到已分配目录；`lessons`键为`course_id:lesson_id:courseware_id`，值含课程/课时ID名称、状态、资源、已分配相对目录、错误/警告。账号范围在清单文件和完整owner校验中体现，当前没有导出类型维度。
- 资源以去除常见轮转鉴权参数后URL的SHA-256作为键，保存 `order/slide_id/page/path/status/size/sha256/format/width/height`、重试计数等；`duplicate`可引用其他完整文件。不要通过目录文件名排序重建PDF顺序。
- 清单保留已分配目录，名称发生变化不会自动重建目录。图片按课时内资源/内容去重，因此后续PDF须按明确页序关联资源和重复引用，不能简单glob图片后合并。
- 所有JSON通用读取目前只接受 `schema_version==1`。后续新账号配置应单独定义读取与兼容规则，不能全局提高schema后使V1清单不可读。
- 检查到7份历史任务清单均为schema1，合计9个complete、7个no_images、2个failed记录；失败来自既有测试/进行中课堂，保留为基线事实，不归因于尚未开始的升级。

## 真实页面依据

本轮沿用实际定位：入口 `/v2/web/index`、role tab精确“我听的课”、`#pane-student .lesson-cardS`；归档 `.archiveDialog/.archiveCardS`；日志 `/v2/web/studentLog/{classroom_id}`、`.studentLog__view`、`.viewContainer`滚动，以模型`hasMore=false`确认结束。

习题正常路由 `/v2/web/student-lesson-report/{course_id}/{courseware_id}/{lesson_id}`；报告原有 `iframe.lesson-report-mobile`中的`.courseware-cmp-wrap`，`.tab-wrap`精确“习题”，`.slides-list .slide-item`内`.slide-img`。报告响应、只读模型与可见DOM交叉核对。没有新建iframe或绕过鉴权。

V1没有缓存“习题/课件”四态或完整课件入口。元数据中已有`courseware_id`不等同于已确认有课件或有权限导出完整课件。**本阶段没有检查或实现课件打印/PDF方案**，留待V2阶段3真实页面验证。

## 本轮基线验证

环境：Windows11、64位Python3.14.7，Playwright1.56.0、Pillow11.3.0，实际浏览器Chrome。Python3.9语法测试通过，不能据此声称Python3.9/Windows10实机通过。

| 验证 | 本轮结果 |
| --- | --- |
| `python -m unittest discover -s tests -v` | 25项全部通过，含真实快照、三态树、主线程约束、窗口布局、原子保存、锁、损坏文件等 |
| `pip check` | 通过，无损坏依赖 |
| `main.py --cached` | 正常退出，现有完整缓存63班级/337课堂 |
| 原单账号会话恢复 | 两个先后新context均从实际页面确认登录、核对账号，无需重新输入密码 |
| 当前真实课程目录 | 普通38、归档25；没有本次全量重扫337课堂的宣称 |
| 真实课程分页抽查 | 工程经济学读取20条、页次[1,2]、hasMore=false；只在内存抽查，不写旧缓存 |
| 真实下载 | 独立测试输出选择一个有习题课堂和一个已结束无习题课堂；成功2/2、保存14张JPEG、无图1、无空课时目录 |
| 新进程式会话恢复与重跑 | 关闭第一个context后再开；保存0、完整性跳过14；图片内容和mtime保持不变 |
| 历史保护 | 106个已有配置、缓存、任务清单和图片文件逐个SHA-256前后相同；源码业务文件与Git基线相同 |

本轮证据 `.local/v2_stage0/20261029_133012/live_baseline.json`；脚本 `tools/verify_v2_baseline.py` 仅做阶段0核验，不参与正常启动。它以现有真实缓存/历史无图记录选样，不构造模拟网页数据。未重新制造损坏图片或重复全部历史停止故障；这些本轮仅跑原回归，先前真实验收见 `TEST_REPORT.md`。

## 升级前已有问题与验证边界

1. 本机内置Chromium启动失败，自动回退Chrome后功能通过；本轮再次重现，未修复系统或浏览器安装。
2. 正在进行中的课堂报告不可用，V1记录明确失败，需课后重扫；这不是升级引入的问题。
3. 当前测试25项中部分依赖本机私人快照/下载样例，交付包只含6项基础测试；不能将6项基础测试作为全部在线功能验收。
4. PDF、资源四态、账号管理/隔离当前都未实现，属于V2新增功能。V1有owner核对和清单隔离，但不能声称多账号已安全切换。
5. 真实验证码、429、权限变化、Cookie过期恢复尚未端到端验收；其他域名、非JPEG/特殊渲染、Windows10/Python3.9实机边界沿用V1记录。
6. 历史项目状态中“界面标题为阶段3”等旧阶段文字与最终GUI不同，以实际代码和最新阶段记录为准。旧验证脚本按“首课时”选样时可能选到后来新增的进行中课时，不能直接用这种选样失败判定下载退化。

## 后续最小增量边界（未实施）

- 阶段1：新增本地稳定账号ID及显示名注册表；把旧站点路径登记为默认兼容账号，原地复用而不移动/复制覆盖旧资料。新账号独立profile/cache；切换等待工作线程结束、清队列和树，重建对应worker。账号重命名只改显示字段；删除需二次确认、校验该账号目录归属，不能触及下载资源。
- 新账号输出可采用V2目录，已登记输出目录与任务键绑定稳定ID；备注名改变不重新计算已分配路径。旧账号图片默认路径和schema1清单继续可用，不能靠目录备注名区分账号。
- 阶段2：复用提取/下载/完整性/原子保存；从明确顺序及完成记录构建合集；PDF-only仅使用本次专用临时目录，不能清理历史图片。图片与PDF独立状态和统计；新PDF校验/依赖待该阶段选型。
- 阶段3：先检查实际课件入口、总页数、原生导出和打印范围；尚无证据证明`page.pdf()`会包含全部课件页，不预定实现或成功标准。
- 阶段4：同一套V1基线回归，加新账号隔离、三项功能组合、停止/重跑、PDF页数/顺序/有效性和文件保护验证。

阶段0结束，等待阶段1指令。当前没有关键登录阻塞，尚未启动任何V2业务升级。
