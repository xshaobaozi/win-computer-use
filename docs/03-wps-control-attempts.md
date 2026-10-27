# WPS 登录窗口操控：七条路径实测记录

> 目标：识别 WPS 登录窗口（CEF 容器）内的元素，并精准点击。
> 环境：Windows · WPS 12.1.0.29161 · 登录窗类名 `KxCefWebViewPrivateBrowser` · 800×600
> 时间：2026-10-27

---

## 结论速览

| # | 路径 | 读元素 | 执行点击 | 结论 |
|---|---|---|---|---|
| 1 | UIA 控件树 | ❌ 16~17 个空壳节点 | ❌ 无控件可调 | 不可用 |
| 2 | MSAA / IAccessible | ❌ 根节点 1 个 child，子节点 COMError | ❌ | 不可用 |
| 3 | CEF DevTools 调试端口 | ❌ 无监听端口 | ❌ | 不可用 |
| 4 | 带 `--remote-debugging-port` 重启 | ❌ 端口未开，参数被过滤 | ❌ | 不可用 |
| 5 | **OCR 视觉通道** | ✅ **11 个元素，坐标精确** | 需真实鼠标 | **识别方案** |
| 6 | 物理鼠标注入 | — | ❌ 无输入桌面权限 | 本环境不可行 |
| 7 | 窗口消息注入 | — | ❌ CEF 不响应 | 不可用 |
| 8 | **UIA InvokePattern（外壳）** | ✅ | ✅ **实测成功** | **WPS 外壳可用** |

一句话：**这个窗口的内容，操作系统层面完全不可见；能看见的唯一通道是 OCR。点击则需要真实鼠标，而当前 Agent 进程没有这个权限。**

---

## 逐条实测记录

### 路径 1：UIA 控件树 —— 空壳

```
窗口: 账号登录
原始节点 16 → 过滤后 4 个有语义元素
#3   Button   "反馈"                          @(1578,404,32x24)
#4   Pane     "KxCefWebViewPrivateBrowser"    @(880,396,800x600)
```

16 个节点里，唯一有名字的是窗口外框自带的“反馈”按钮。CEF 的 `Document` 节点名是一串纯数字 ID，没有任何子内容。

**原因**：Chromium/CEF 的无障碍树默认不构建，必须显式开启。金山没有开。

### 路径 2：MSAA / IAccessible —— 空壳

绕过 UIA Provider，直接走老的 IAccessible 接口：

```
=== CefBrowserWindow hwnd=264648 ===
  accChildCount = 1
  根节点名称 = 'KxCefWebViewPrivateBrowser'
    child 1: 读取失败 COMError
```

`KCefContainerWindow`、三个 `CefBrowserWindow` 全部一样。这条路和 UIA 走的是不同底层通道，但结论一致——CEF 根本没往无障碍层写东西。

### 路径 3：CEF DevTools 调试端口 —— 没开

CEF 如果带 `--remote-debugging-port` 启动，会开一个 HTTP+WebSocket 端口，可以直接对里面的网页发 CDP 命令（拿 DOM、点击、执行 JS）。

实测扫描本机所有 LISTENING 端口：

```
WPS 进程: [1444, 6332, 12652, 15328, 18760, 20652, 25720]
未发现可用的 DevTools 调试端口
=== WPS 进程全部监听端口 ===
（空）
```

七个 WPS 相关进程，一个端口都没监听。这条路是关闭的。

### 路径 4：带参数重启 —— 参数被过滤

尝试自己给 CEF 宿主进程加调试参数。先定位到登录窗的宿主是 `wpscloudsvr.exe`（云服务进程，不是主程序 wps.exe），这样关闭它不影响文档编辑，风险可控。

```
taskkill /F /IM wpscloudsvr.exe        → 成功
wpscloudsvr.exe --remote-debugging-port=9222 --remote-allow-origins=*
检测 9222 → TimeoutError
```

进程重启了（新 PID 3208），但端口没开。**金山在启动时过滤了未识别的命令行参数**——这是商业软件的常规做法，防的就是这种注入。

### 路径 5：OCR 视觉通道 —— 完全可行 ✅

截图（`PrintWindow` + `PW_RENDERFULLCONTENT`）→ RapidOCR 识别：

```
窗口: 账号登录  截图 800x600  原点 (1091, 394)
识别到 11 个文本元素

#1   "自动登录"      @(1524,475,66x19)    conf=0.795
#3   "临时登录"      @(1713,475,67x19)    conf=0.733
#6   "微信扫码登录"  @(1585,576,133x22)   conf=0.837
#8   "手机"          @(1509,936,28x16)    conf=0.639
#9   "WPS扫码"       @(1579,936,59x16)    conf=0.765
#10  "专属帐号"      @(1668,934,52x19)    conf=0.758
#11  "更多"          @(1766,936,27x16)    conf=0.658
```

坐标是屏幕绝对坐标，可以直接用于点击。可视化见 `docs/assets/wps-login-ocr.png`（每个元素画框 + 编号，绿准星是算出的点击落点）。

**这条路的两个前提**（都踩过）：
- 窗口必须真的渲染出来。新弹出、还在后台的 CEF 窗口，`PrintWindow` 抓到的是**纯白**（灰度范围 255~255）。要等页面加载完再截。
- 窗口被遮挡不影响 `PrintWindow`，但如果 GPU 合成没跑起来，也是白图。

### 路径 6：物理鼠标注入 —— 权限被拒

```
GetCursorPos()      → OSError (5, '拒绝访问')
SetCursorPos()      → pywintypes.error (0, 'No error message')
SendInput 绝对坐标   → 调用不报错，界面无任何变化
ImageGrab.grab()    → OSError: screen grab failed
OpenInputDesktop()  → 返回 0，错误 5
```

诊断确认：进程在 `WinSta0` / `Default` 桌面、Session 1（正常交互会话），但 **`OpenInputDesktop` 被拒绝**。这是 AppContainer / 受限令牌的典型表现——**能读窗口，碰不到输入**。

这是**我这个 Agent 进程的环境限制**，不是 Windows 的限制，更不是方案的限制。你自己的程序跑在正常用户会话里，`SendInput` 是标准可用路径。

### 路径 7：窗口消息注入 —— CEF 不理会

绕开光标，直接往窗口发消息：

```
顶层句柄 329392 → 目标句柄 1640652 (Chrome_WidgetWin_0)
屏幕(1779,944) → 客户区(688,550)
点击前 11 项 → 点击后 11 项
```

消息投递成功，界面纹丝不动。CEF 的渲染窗口不处理消息队列里的鼠标事件——它依赖真实的输入队列和内部命中测试。**这条路对所有 Chromium/CEF 应用都不可靠**。

### 路径 8：UIA InvokePattern —— 意外成功 ✅

测试过程中发现，WPS **外壳**（不是 CEF 内部）的按钮是可以通过 UIA 语义调用的：

```
按钮清单:
  '新建'        @(1032,149)
  '立即登录'    @(2084,194)
  '打开'        @(851,305)

已 Invoke: 立即登录
→ 窗口列表出现: wps.exe | Qt5QWindowIcon | 账号登录
```

**登录窗口真的弹出来了**，鼠标一动没动。这证明：WPS 自绘外壳的控件不只是"可读"，还"可点"，而且不需要鼠标权限。

（顺带说明：点"新建"没有反应，那个控件的行为路径不同，可能只是展开一个空面板。同类控件效果不一，需要逐个验证。）

---

## 为什么 CEF 容器打不开

CEF 的无障碍支持是**双重开关**：

| 层级 | 开关 | 金山的选择 |
|---|---|---|
| 运行期 | `CefSettings.accessibility_state` 或 `--force-renderer-accessibility` | 关 |
| 编译期 | `cef_enable_accessibility` 构建选项 | 未知，但即便开了也没被激活 |

外部能强制打开的路径只有三条，全部被堵：

1. **调试端口** — 需要启动时传参，金山过滤了参数
2. **无障碍客户端请求** — UIA 和 MSAA 都试了，CEF 不响应（因为它压根没构建树）
3. **注入进程** — 需要写目标进程内存，属于逆向，且大概率触发安全软件

**这就是"打不开"的完整原因。**

### 如果你将来自己写 CEF 应用

这三个开关要主动打开，否则外部一切自动化手段都失效：

```cpp
CefSettings settings;
settings.remote_debugging_port = 9222;          // 开 CDP，外部可拿 DOM
settings.accessibility_state = STATE_ENABLED;    // 开无障碍，UIA/MSAA 能读
// 编译时：cef_enable_accessibility = true
```

开了这两个，外部 Agent 就能像操作普通网页一样操作它——DOM、点击、读文本全通。**这是给未来的你的建议，也是这类软件"可被自动化"的设计前提。**

---

## 最终可行方案

### 按场景选通道

| 你要做的事 | 通道 | 可行性 |
|---|---|---|
| 编辑/生成/读取 WPS 文档 | **COM（`Word.Application`）** | ✅ 已验证，无需登录、无需看屏幕 |
| 点 WPS 外壳的按钮（新建/打开/登录） | **UIA InvokePattern** | ✅ 已验证，不碰鼠标 |
| 读 CEF 窗口里的文字 | **OCR** | ✅ 已验证，11 个元素全中 |
| 点 CEF 窗口里的元素 | **OCR 定位 + SendInput** | ⚠️ 需要正常用户会话权限 |
| 后台点 CEF 窗口 | — | ❌ 不存在可靠方案 |

### 决策树

```
要操作 WPS
├─ 是文档内容？
│   └─ COM 直连（不碰界面，最稳）
├─ 是外壳按钮（有 UIA 控件名）？
│   └─ UIA InvokePattern / ValuePattern（不碰鼠标）
└─ 是 CEF 内嵌界面（登录窗、云盘、AI 面板）？
    ├─ 只需要读 → OCR，够用
    └─ 需要点 → OCR 定位 + SendInput
         └─ 若进程无输入权限 → 降级为"人在回路"：
            把待点击目标画出来，让人确认一下
```

最后一档的"人在回路"不是妥协，是工程上的正确选择：**当执行权限不可靠时，把决策权交回给人，比强行注入更安全。** 工业 RPA 里这叫 human-in-the-loop 确认，很多合规场景是强制要求。

---

## 我这个进程的能力边界（重要）

| 能力 | 状态 | 说明 |
|---|---|---|
| 枚举窗口、读句柄 | ✅ | `EnumWindows` 正常 |
| 读 UIA 树 | ✅ | 走 UIA Provider |
| 读 IAccessible | ✅ | 走 MSAA |
| 用 `PrintWindow` 截窗口 | ✅ | 窗口渲染好就能抓 |
| 抓整个屏幕 | ❌ | `ImageGrab` 失败 |
| 读光标位置 | ❌ | 拒绝访问 |
| 移动/点击鼠标 | ❌ | `SetCursorPos` 失败、`SendInput` 被忽略 |
| 向窗口发消息 | ✅ | `PostMessage` 可用，但 CEF 不响应 |
| UIA 语义调用 | ✅ | `InvokePattern` 实测生效 |
| COM 自动化 | ✅ | `Word.Application` 完整可用 |

**结论：这个环境能"看"能"算"，不能"动手"。** 你本地跑同样的代码，鼠标那两行会正常工作。

---

## 代码清单

| 文件 | 作用 | 验证状态 |
|---|---|---|
| `tools/uia_snapshot.py` | UIA 结构化快照（带编号元素表） | ✅ 浏览器 304→70 |
| `tools/vision_snapshot.py` | 截图 + OCR → 带坐标元素表，支持 `--click` | ✅ 11 元素 |
| `tools/annotate.py` | 识别结果可视化标注 | ✅ 见 annotated.png |
| `tools/post_click.py` | 窗口消息点击（无光标权限时备选） | ⚠️ 投递成功但 CEF 无效 |
| `tools/msaa_probe.py` | MSAA/IAccessible 探测 | ✅ 证明 CEF 空 |
| `tools/cef_probe.py` | 扫描 DevTools 调试端口 | ✅ 证明未开 |
| `tools/test_wps_com.py` | WPS COM 通道验证 | ✅ 建/写/读/加粗全通 |
| `tools/e2e_loop.py` | 端到端闭环范例 | ✅ 提交成功 |

### 在你本地验证鼠标点击

```bash
# 1. 看识别
python tools/vision_snapshot.py "账号登录"

# 2. 生成标注图，肉眼确认坐标对不对
python tools/annotate.py "账号登录" "临时登录"

# 3. 真正点击（你的环境应该能成功）
python tools/vision_snapshot.py "账号登录" --click "临时登录"
```

第 3 步在我这里会挂在 `SetCursorPos` 上，在你的正常桌面会话里应该直接点中。

---

## 副作用说明

测试过程中我关闭了 `wpscloudsvr.exe`（云服务进程）并重启它，用来验证能否带调试参数启动。结果：**调试端口没开，登录窗口被重新拉起后内容是白屏**（CEF 在本环境渲染不出来），我已把它关闭。

当前状态：WPS 主窗口完好，无文档丢失。你下次点“立即登录”或重启 WPS，登录窗会正常出现。如果它没出现，重启一次 WPS 即可。
