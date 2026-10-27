# Windows 远程操控 Agent 技术方案（局域网双机）

> 目标：主控电脑 A 上的 Agent 通过局域网 IP 连接被控电脑 B，B 上常驻一个 Server 负责"感知屏幕 + 注入键鼠 + 执行校验"，A 负责规划与决策。
> 结论：完全可行。屏幕识别与输入注入都有官方 API，GitHub 上有多个可直接复用或借鉴的开源实现。

---

## 一、整体结论

| 问题 | 结论 |
|---|---|
| 能否精准识别屏幕内容 | 能。但不是"一个方法搞定"，要按"结构化信息 > 文字 OCR > 视觉定位"三级降级 |
| 能否模拟鼠标键盘 | 能。官方 SendInput 覆盖 95% 场景，剩下靠 UIA 控件模式或内核级注入补齐 |
| 局域网 IP 远程操控是否可行 | 可行，且是这类系统最常见的部署方式（被控端起 Server，主控端连过来） |
| 是否有现成方案 | 有。分两类：① 完整 Agent 产品（可直接用）② 只做"手和眼"的 Server / MCP（最适合你改造） |
| 最该抄的架构 | 微软 UFO² 的 "UIA 树 + 视觉解析" 混合感知，配 opendesk / Cua 的本地-远程同构接口 |

---

## 二、屏幕感知：三级精度金字塔

纯截图喂大模型是最容易做、也最容易飘的做法。生产级系统都是**先走结构化、再走视觉**。

### 第 1 级：UI Automation 树（Windows 原生的"屏幕语义"）

Windows 有一个为无障碍设计、但也能被自动化程序读的接口：**UI Automation（UIA）**。它能把当前屏幕上的窗口拆成一棵控件树，每个节点带：

- 控件类型（按钮 / 编辑框 / 菜单项 / 列表项 / 标签页…）
- 可读名称、AutomationId、类名
- 屏幕矩形包围盒（BoundingRectangle）
- 是否可用、是否被选中、当前值（ValuePattern）
- 支持哪些操作模式：`InvokePattern`（点击）、`ValuePattern`（赋值）、`TogglePattern`（勾选）、`SelectionItemPattern`（选择）、`ExpandCollapsePattern`（展开）、`ScrollPattern`（滚动）

这是**精度最高、token 最省、速度最快**的一层。拿到 `BoundingRectangle` 就直接知道按钮中心点坐标，不需要猜像素。

技术选型：
- C# / .NET：`System.Windows.Automation` 或 `FlaUI`（封装更好用）
- Python：`uiautomation`（推荐，能 dump 整棵树）、`pywinauto`（偏控件操作）
- 直接调 COM：`IUIAutomation`，性能最好，适合做常驻服务

局限（必须知道）：
- 部分应用不暴露自身 UI：游戏、自绘 Canvas（Figma/PS 画布区）、部分 Java/Qt 老程序、某些 Electron 内嵌 webview
- Chromium / Electron 应用默认不暴露网页内容，需要加启动参数 `--force-renderer-accessibility`，或者改用 CDP（Chrome DevTools Protocol）读 DOM
- 有 UIPI 隔离：以管理员权限运行的窗口，非管理员进程读不到 / 点不了（见第四节）
- 树可能很大：整个桌面 dump 一次几千个节点，必须做窗口级裁剪 + 只取可交互节点

### 第 2 级：OCR + 模板匹配（兜底文字和图标）

UIA 拿不到时，用传统 CV 补：

- OCR：`Windows.Media.Ocr`（系统自带，中英文可用，零依赖）、`PaddleOCR`（中文更强）、`Tesseract`（老牌但中文一般）
- 模板匹配：`OpenCV matchTemplate`，适合图标、按钮这类像素稳定的元素
- 颜色/边缘检测：适合找"某个颜色的按钮""某条分割线"

这层输出的是"文字 → 屏幕坐标列表"，对表格、报表、日志窗口这类信息化界面很有用。

### 第 3 级：视觉定位模型（真正"看懂"界面）

当界面完全无法结构化（游戏、远程桌面画面、复杂设计工具）时，才动用视觉模型：

- **截图 → 元素框 + 描述**：微软 `OmniParser`（YOLO 检测可交互区域 + Florence 生成功能描述），输出带编号的标注图（set-of-marks）。V2 在单张 4090 上约 0.8s/帧，ScreenSpot-Pro 39.6%。它本身不做决策，只负责"把像素变成结构化元素列表 + 编号"，然后让任意 VLM 去选编号。
- **端到端 GUI grounding 模型**：`UI-TARS`（字节）、`SeeClick`、`UGround`、`ShowUI`，输入截图 + 指令，直接输出坐标。
- **通用 VLM**：GPT-4o / Claude / Qwen-VL / 豆包，配合 set-of-marks 效果最好（不要让模型自己数像素）。

关键技巧：
1. **set-of-marks**：在截图上给每个候选元素画编号框，让模型输出编号而不是坐标，准确率远高于让模型算像素。
2. **坐标归一化**：把点击坐标归一化到 0–1000 或 0–1 再让模型输出，避免分辨率变化导致漂移。
3. **单步单动作**：一次只让模型输出一个动作，执行后重新截图确认，不要让它一次规划十步然后连点。

### 三级怎么组合（推荐）

```
要操作某个控件
  ├─ 1. UIA 树里按 name / AutomationId 精确查找 ──► 命中：用 BoundingRectangle 中心点，或直接调 InvokePattern
  ├─ 2. 没命中 → 当前窗口 UI 树局部 + OCR 文本定位 ──► 命中：得到文字框坐标
  └─ 3. 还没有 → 截图 + OmniParser / VLM 视觉定位 ──► 得到候选元素 + 编号
每次动作后：截图 / 读关键属性，确认状态真的变了，再走下一步
```

实测经验：一级能覆盖大部分常规桌面软件（Office、浏览器、资源管理器、设置），二级补上微信/QQ/钉钉这类 Electron/CEF 重绘界面，三级只用于兜底。全部走三级的话，单步延迟 1~3 秒、成本高、坐标还容易偏。

---

## 三、坐标精度：最容易翻车的地方

| 坑 | 现象 | 解法 |
|---|---|---|
| DPI 缩放 | 125%/150% 缩放下点击整体偏移 | 进程声明 Per-Monitor V2 DPI 感知（manifest `<dpiAwareness>PerMonitorV2</dpiAwareness>`）；统一在**物理像素**空间计算坐标；UIA 只支持一次 DPI 感知，跨屏要手动换算 |
| 多显示器 | 副屏点不到、负坐标异常 | 用 `EnumDisplayMonitors` 拿每块屏的原点和缩放；坐标允许为负；截图要拼接或按屏分别截 |
| 截图与坐标空间不一致 | 截图 2560 宽，逻辑坐标 1700 | 明确三套空间：逻辑坐标 / 物理像素 / 截图图像坐标，代码里只允许在边界处换算一次 |
| 窗口移动 | 定位到点击之间窗口被拖动 | 定位后立刻校验目标窗口 `GetWindowRect` 未变；建议点击前先 `SetForegroundWindow` 激活 |
| 浮动弹层 | 点击落空 | 动作后强制重新感知，不要复用上一帧坐标 |

---

## 四、执行层：鼠标键盘怎么"真"注入

| 方式 | 原理 | 需要前台 | 兼容 UWP | 绕过 UIPI | 能否后台 | 适用 |
|---|---|---|---|---|---|---|
| **SendInput** | 注入系统输入流，等同真实硬件 | 是 | ✅ | ❌ | ❌ | 默认方案，覆盖绝大多数软件 |
| **PostMessage / SendMessage** | 直接往目标窗口消息队列投 `WM_LBUTTONDOWN` / `WM_KEYDOWN` | 否 | ❌（无子 HWND 会丢弃） | ❌ | ✅ | 后台操作传统 Win32 / WPF，不抢鼠标 |
| **UIA Pattern（Invoke / Value / Toggle）** | 调控件的语义操作接口 | 否 | ✅ | 受权限限制 | ✅ | 最稳，优先用；不移动鼠标、不抢焦点 |
| **Interception 内核驱动** | 在驱动层伪造 HID 设备 | 是 | ✅ | ✅ | ❌ | 游戏、反作弊、RawInput 程序 |
| **剪贴板粘贴** | 写剪贴板 + 发 Ctrl+V | 是 | ✅ | — | ❌ | 输入中文/长文本，绕开 IME 与逐字符输入问题 |

实战要点：
- **输入文本优先用 ValuePattern 直接赋值**，不行再剪贴板粘贴，最后才逐字符 `SendInput`。逐字符输入中文容易丢字、乱码。
- **不要用固定 sleep 等界面**。改为轮询状态：点击后等"窗口出现新子元素 / 目标属性变化 / 特定文字出现"，带超时和重试。这是 Agent 稳不稳的分水岭。
- **UIPI 与权限**：如果目标程序以管理员运行，你的 Server 也必须是管理员（或在同一完整性级别），否则读不到树、点击被静默丢弃。
- **Session 隔离**：Windows 服务运行在 Session 0，看不到用户桌面。Server 必须以**当前登录用户的交互式进程**运行（托盘程序 / 自启脚本 / 计划任务勾选"只在用户登录时运行"），不能做成 Windows 服务。
- **UAC 安全桌面**：提权确认框在 Secure Desktop，程序无法点击。必须人工确认或提前配置免 UAC。

---

## 五、局域网双机架构

### 部署形态

被控端 B：常驻 Server（Python / .NET / Node 都可），监听内网端口，暴露"感知 + 执行"原子能力；不做决策。
主控端 A：Agent 进程，跑大模型规划，通过 WebSocket 调 B 的能力。

这种"接口同构"设计很重要：让同一套工具既能操作本机也能操作远端。`opendesk` 和 `Cua` 都是这个思路——`LocalComputer` 和 `RemoteComputer` 实现同一个抽象类，上层工具不知道机器在本地还是远端。

### 协议建议

- 传输：**WebSocket**（双向、低延迟、天然支持服务端推事件）。别用纯 HTTP 轮询，截图轮询延迟高。
- 编码：JSON 用于控制指令；帧数据用 **msgpack** 或裸二进制，不要 base64（体积 +33%）。
- 端点划分：
  - `/ws/control` 指令与响应（截图请求、点击、输入、查询 UI 树）
  - `/ws/stream` 屏幕流（如果要做实时画面）
  - `/ws/events` 服务端主动事件（窗口切换、焦点变化、任务中断）

### 消息示例

```jsonc
// A → B
{ "id": "r17", "op": "capture", "args": { "display": 0, "scale": 1.0, "marks": true } }
{ "id": "r18", "op": "uia.query", "args": { "hwnd": 123456, "role": "button", "name": "保存" } }
{ "id": "r19", "op": "click", "args": { "x": 812, "y": 344, "button": "left", "space": "physical" } }
{ "id": "r20", "op": "type", "args": { "text": "季度报表", "method": "clipboard" } }

// B → A
{ "id": "r17", "ok": true, "data": { "w": 2560, "h": 1440, "dpi": 144, "image": "<bin>", "elements": [{"i":1,"role":"button","name":"保存","box":[790,330,46,28]}] } }
```

### 带宽估算

| 方式 | 1080p 单帧 | 1 fps | 5 fps |
|---|---|---|---|
| PNG 无损 | 1.5–4 MB | 2–4 MB/s | 吃满千兆 |
| JPEG q75 | 150–300 KB | 0.2–0.3 MB/s | 1–1.5 MB/s |
| H.264 硬编 | — | 0.3–1 Mbps | 2–4 Mbps |

结论：**Agent 场景不需要视频流**。默认 1~2 fps 的 JPEG 按需截图 + 差量（只传变化区域）就够；只有需要"人在主控端实时看"时才上 H.264（可直接借用 Sunshine / Chromium Remoting / WebRTC）。

### 安全（内网也不能省）

1. **不要裸奔 0.0.0.0 + 无认证**。这个 Server 的权限 = 你的 Windows 账户权限，被同网段任何设备连上就是整机失控。
2. 首次配对：被控端屏幕上显示 6 位配对码，主控端输入 → 交换公钥（X25519）→ 之后走 TLS + token 或 mTLS。
3. 只绑内网网卡；开防火墙规则限定来源 IP 段；禁止端口映射到公网。
4. 高危动作白名单/确认：删除文件、执行任意命令、访问特定站点，需要人工确认。
5. 审计日志：谁在什么时候执行了什么动作 + 截图，可回溯。
6. 主控端断连自动停止（dead man's switch）；提供全局急停热键（如 Ctrl+Alt+Esc 立即释放输入控制）。

---

## 六、GitHub 现有方案盘点

> 星标数量级仅供参考（2026-10 检索），以仓库实际为准。

### A 类：完整 GUI Agent（可直接用，也可整体改造）

| 项目 | 特点 | 对你的价值 |
|---|---|---|
| **bytedance/UI-TARS-desktop**（3 万+ ⭐，TypeScript，Apache-2.0） | 字节的桌面 Agent 全栈：截图 → VLM → 键鼠动作闭环，支持本地/远程接管、MCP、可换任意模型 | 想快速跑通 Demo 首选；架构是"纯视觉"，可以对照补上 UIA 层 |
| **Agent TARS**（同仓库） | CLI + Web UI，浏览器支持 GUI / DOM / hybrid 三种策略 | 浏览器部分可直接复用 hybrid 思路 |
| **microsoft/UFO（UFO²/UFO³）**（1 万+ ⭐，Python，MIT） | **Windows 专用**：HostAgent 拆任务 + AppAgent 专项执行；UIA 树 + 视觉解析混合感知；可直接调 Win32/COM 原生 API 而不是点界面；支持多机协同（Galaxy 走 WebSocket + 任务图） | **与你需求最贴、最该精读的架构**。混合感知 + GUI/API 双通道，正是"精准识别"的答案 |
| **trycua/cua**（1.8 万+ ⭐，MIT） | 一套 API 控制 Win/macOS/Linux/Android 沙箱；`computer-server` 暴露 HTTP + WebSocket + MCP 端点；Driver 可后台操作不抢鼠标焦点 | **远程 Server 的现成实现**，直接看它的端点设计和 driver 思路 |
| **CursorTouch/Windows-MCP** | 轻量 MCP Server，直接走 UIA + SendInput，19 个工具（click/type/screenshot/snapshot/app/powershell/registry…），不依赖视觉模型，单步 0.2–0.5s | 想"最小可用"，直接接这个当被控端的执行器 |
| **vitalops/opendesk** | 跨平台 computer use 框架，明确支持**加密 WebSocket 控制远端机器**、mDNS 发现、X25519 配对、msgpack 帧、审计日志 | **远程控制部分的最佳参考**，几乎就是你要的协议设计 |

### B 类：只做"眼睛"的组件（嵌进你自己的系统）

| 项目 | 用途 |
|---|---|
| **microsoft/OmniParser**（2.5 万+ ⭐） | 截图 → 可交互元素框 + 功能描述 + set-of-marks 标注图。纯视觉、模特无关，AGPL 部分注意 |
| **UI-TARS / UGround / SeeClick / ShowUI** | GUI grounding 模型，截图 + 指令 → 坐标 |
| **PaddleOCR / Windows.Media.Ocr** | 文字定位 |
| **FlaUI / uiautomation / pywinauto** | UIA 树读取与控件操作（C# / Python） |
| **Interception** | 内核级键鼠注入 |
| **Sunshine / Chromium Remoting** | 需要实时画面时的低延迟串流 |

### C 类：另一个思路——录制回放

**OpenAdapt**：人演示一遍，自动转成可审计的工作流，重复任务不调用大模型，确定性执行。适合"固定流程、要求稳定"的场景，可与你 Agent 并行：常规流程走回放，异常才走大模型。

---

## 七、建议的实现路线

### 阶段 0：验证可行性（1~2 天）
- B 端起一个 Python FastAPI + WebSocket，暴露 `capture` / `click` / `type` / `query_uia` 四个接口
- A 端用脚本走通"截一张图 → 传过去 → 点一个按钮 → 再截图确认"
- 验收：能在 B 上打开记事本、输入中文、保存文件

### 阶段 1：混合感知（1~2 周）
- 接 UIA dump，做窗口级裁剪 + 只保留可交互节点
- 实现"按 name/AutomationId 查找 → 返回包围盒 → 点击"的快路径
- 兜底接 OCR
- 验收：常规软件里定位准确率 > 90%，单步 < 800ms（不含模型）

### 阶段 2：视觉兜底（1~2 周）
- 接 OmniParser 或 VLM + set-of-marks，处理 UIA 失效的界面
- 建立"哪些窗口走 UIA、哪些走视觉"的路由表
- 验收：Canvas / Electron 场景也能点中

### 阶段 3：Agent 化（2~4 周）
- 任务规划、动作校验、失败重试、上下文压缩（截图别全塞进历史）
- 权限护栏、审计日志、急停
- 验收：连续 20 步复杂任务成功率可接受，可断点续跑

---

## 八、坑清单（踩过的人都在这里翻车）

1. **Windows 服务看不到桌面** —— 必须用交互式用户进程。
2. **DPI 没声明** —— 高缩放机器上点击整体偏移，且只在部分机器复现。
3. **管理员窗口读不到** —— UIPI 隔离，非提权进程静默失败。
4. **Chromium 内容为空** —— 需要 `--force-renderer-accessibility` 或走 CDP。
5. **固定 sleep** —— 界面没加载完就点，随机失败；必须状态轮询。
6. **模型一次给多步** —— 出错无法定位；单步 + 校验。
7. **截图不压缩** —— 一张 4K PNG 塞进上下文，token 爆炸、延迟爆炸。
8. **把鼠标抢走** —— 有人用电脑时冲突；用 UIA Pattern / PostMessage 做后台操作，或提供"接管/释放"模式。
9. **无认证的局域网端口** —— 同网段任何人都能控制整机。
10. **中文输入** —— 逐字符 SendInput 会丢字，用剪贴板或 ValuePattern。

---

## 九、一句话建议

先不要把"识别"当核心难题——**把它当成分级路由问题**：能用 UIA 的走 UIA（快、准、省），不能的走 OCR，再不能的走视觉模型。这块直接精读 `microsoft/UFO` 的混合感知实现。

远程部分不用自己设计协议，`vitalops/opendesk`（加密 WebSocket + 配对 + msgpack + 审计）和 `trycua/cua` 的 `computer-server`（HTTP/WS/MCP 三套端点 + 后台 driver）已经把该踩的坑踩完了，照抄结构即可。

真正需要你自己投入的，是**动作后的状态校验**和**失败恢复策略**——这两件事决定它是个玩具还是个能干活的工具。
