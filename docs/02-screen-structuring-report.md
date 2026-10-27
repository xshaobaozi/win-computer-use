# 屏幕信息结构化 + 精准操控：本机实测报告

> 实测环境：Windows 桌面 · WPS Office 12.1.0.28802 · Chrome 155.0.8059.85 · Python 3.13
> 测试时间：2026-10-27
> 结论全部来自本机真实运行，不是纸面推演。

---

## 一、先纠正一个普遍误解

"把屏幕结构化告诉 Agent" —— 很多人理解成**用自然语言描述屏幕内容**（"屏幕上有一个输入框，旁边写着客户名称……"）。

这是错的。自然语言描述既贵又不精确，模型还得再从描述里猜位置。

正确的结构化是**把界面编译成一张带稳定标识的可操作对象表**：

```
#36  Edit      "客户名称"   @(158,176,256x28)
#40  Button    "提交订单"   @(58,326,90x34)
#42  Text      "等待提交…"  @(66,502,78x22)
```

每一行就是一个可寻址对象。Agent 做两件事：
- **选**：从表里挑一行（用语义名"提交订单"，不是坐标）
- **读**：从表里读状态（输入框值、文本内容、是否可用）

坐标只是执行时的副作用，**不是 Agent 思考的输入**。这是精准度的根本来源。

### 结构化应该拆成四个正交视图

| 视图 | 内容 | 回答什么问题 |
|---|---|---|
| **元素视图** | id / role / name / bbox / enabled | 点谁？在哪？ |
| **内容视图** | 文本块、表格行列、文档正文 | 现在屏幕上是 What？ |
| **状态视图** | 焦点元素、活动窗口、弹层、滚动位置 | 走到哪一步了？ |
| **差异视图** | 与上一帧比，新增/消失/值变化 | 上一步生效了吗？ |

缺任何一个，Agent 就会"看起来在操作，其实在盲走"。**差异视图是最常被忽略、却决定成败的那一个。**

---

## 二、本机实测：各类应用能被结构化到什么程度

统一口径 = `原始控件节点数 → 过滤后的有效元素数`（可见 + 有语义 + 尺寸有效）。

| 应用 / 窗口 | 技术栈 | 原始节点 | 有效元素 | 正文内容可读 | 判定 |
|---|---|---|---|---|---|
| **Chrome（默认启动）** | Chromium | 235 | 25 | ❌ 网页内容 **0 命中** | 只有外壳，不可用 |
| **Chrome（加 `--force-renderer-accessibility`）** | Chromium | 304 | 70 | ✅ 表单、表格、状态文字全在 | 完美 |
| **WPS 首页**（KPromeMainWindow） | 自绘 | 135 | 12 | ❌ | 只有框架 |
| **WPS 文档窗口**（OpusApp） | 自绘 | 160 | 22 | ❌ **正文完全不在树里** | 只能点到菜单栏 |
| **WPS 登录窗**（KWebView） | WebView | 37 | 6 | ❌ | 不可用 |
| **Electron 应用**（WorkBuddy） | Electron | 603 | 176 | ✅ | 取决于开发者是否开启 accessibility |
| **WPS COM 接口** | COM | — | — | ✅ 直接读写文档对象 | **最佳通道** |

### 关键发现

**1. Chromium 必须显式开无障碍，且不是"等一会儿就好"**
默认启动的 Chrome 我连续探测三次、间隔 3 秒，稳定停在 235 个节点、网页内容 0 命中——全是浏览器外壳（工具栏、书签栏）。加 `--force-renderer-accessibility` 后立刻变成完整表单：输入框、下拉框、复选框、按钮、表格单元格、状态文字，一个不少，还带精确坐标。

**2. WPS 是自绘界面，UIA 只能拿到菜单栏那一层**
WPS 文档窗口 160 个节点里，能用的只有"文件/开始/插入/页面/引用/审阅/视图/工具/WPS AI/100%"这些顶栏入口。**文档正文一个字都读不到**，功能区里的"加粗""字号""表格"也拿不到。这意味着：想靠点界面来编辑 WPS 文档，等于闭着眼睛点。

**3. WPS 有 COM 通道，实测完全可用**
这是我这一轮最有价值的验证。用 `win32com` 连 `Word.Application`（WPS 注册的兼容 ProgID），实测成功：

```
已连接: Word.Application
应用名: Microsoft Word  版本: 12.0
文档已创建，段落数=4
--- 读回内容 ---
季度销售汇总
客户：杭州云图
金额：12800
写入并加粗完成，文档名=文字文稿1
```

创建文档、写入中文、读回正文、设置加粗——全部成功。**这条路完全不需要看屏幕。**

**4. 端到端闭环实测通过**
在测试页上跑了一次完整业务动作（代码见 `tools/e2e_loop.py`）：

```
步骤 1  结构化感知
  输入框: 找到       坐标 (158,176)
  提交按钮: 找到     坐标 (58,326)
步骤 2  填写内容
  通过 ValuePattern 直接赋值成功      ← 没敲键盘
步骤 3  点击提交
  通过 InvokePattern 触发成功（未移动鼠标） ← 没动鼠标、没抢焦点
步骤 4  读取画面反馈
  反馈文本: 提交成功：杭州云图科技 / 0   ← 拿到了结果
步骤 5  验证输入框当前值
  客户名称 = '杭州云图科技'
```

注意步骤 2、3 的方式：**没有模拟键盘、没有移动鼠标**。ValuePattern 直接给控件赋值，InvokePattern 直接触发按钮逻辑。这是精度最高的做法，而且不干扰用户。

---

## 三、三个场景该走哪条通道

### 场景 1：WPS —— 走 COM，别走屏幕

| 通道 | 能力 | 建议 |
|---|---|---|
| **COM（`Word.Application`）** | 读写正文、段落、表格、样式、页面设置、导出 PDF；可读回当前内容作为反馈 | **主力，90% 的需求走这条** |
| UIA | 只能拿到菜单栏一级 | 仅用于点开菜单 |
| 视觉 + 坐标 | 能看能点，但界面改版即失效 | 兜底 |

常用对象与方法：

```python
import win32com.client as win32
app = win32.Dispatch("Word.Application")   # WPS 文字
# 表格：Ket.Application；演示：Kwpp.Application

doc = app.Documents.Open(r"D:\report.docx")
doc.Content.Text                                  # 读全文 = 反馈
doc.Paragraphs(3).Range.Text                      # 读某段
doc.Tables(1).Cell(2, 3).Range.Text               # 读表格单元格
doc.Content.Find.Execute("旧文本")                 # 查找
doc.Range().Find 配合 Replace                      # 批量替换
doc.ExportAsFixedFormat(r"D:\out.pdf", 17)         # 导出 PDF
doc.Save(); doc.Close(False)
```

**什么时候还是得走界面**：各类对话框、插件面板、云文档列表页、WPS AI 侧边栏——这些不在文档对象模型里。策略是 **COM 处理文档内容，UIA/视觉处理对话流程**，按步骤切换。

### 场景 2：浏览器 —— CDP 是唯一正解

| 方式 | 拿得到什么 | 局限 |
|---|---|---|
| UIA + `--force-renderer-accessibility` | 可见区域的元素 + 坐标 | 拿不到隐藏元素、拿不到网络状态、不能执行 JS、不能等待"网络空闲" |
| **CDP（Chrome DevTools Protocol）** | 完整 DOM、无障碍树、布局快照、网络请求、Console、JS 执行 | 需要以 `--remote-debugging-port` 启动；只能控制自己启动的实例 |
| 视觉模型 | 画面像素 | 兜底 |

CDP 的价值在于**不只是"看"，还能"等"**：等某个请求返回、等 DOM 稳定、等网络空闲。这才是"知道反馈"的最强信号。

推荐直接复用 browser-use 的序列化设计（它把 10000+ 节点压到 ~200 个可交互元素、5~10KB 文本），或者用自己的 CDP 客户端按同样思路写。

三个必用 CDP 域：
- `DOM.getDocument` + `DOMSnapshot.captureSnapshot` → 结构 + 布局 + 实时输入值
- `Accessibility.getFullAXTree` → 语义角色和名称
- `Network.enable` / `Page.enable` → 等请求完成、等 load 事件

### 场景 3：微信 —— 最麻烦的一类，要有心理准备

**本机未安装微信客户端**（只装了微信输入法），所以这一项我没法给你实测数据。以下基于开源实现的技术路线分析。

| 路线 | 可行性 | 代价 |
|---|---|---|
| UIA 树（wxauto 做法） | 可行，但**极脆弱** | wxauto 把版本号 `3.9.11.17` 硬编码在源码里，微信一升级控件树就重构，框架直接失效。它还得靠"像素和几何信息猜布局"来补语义缺失 |
| 视觉 + OCR | 通用 | 慢（每步 1~3 秒）、易受主题/缩放影响 |
| Hook / 协议逆向 | 能力最强 | 违反用户协议，封号风险高，不建议 |
| 企业微信官方 API | 稳定合规 | 只能覆盖企业内部沟通，不是个人微信 |

**如果一定要做个人微信**，建议的组合拳：
1. **UIA 定位**：会话列表、输入框、发送按钮（这几个控件相对稳定）
2. **OCR 读消息**：消息气泡区域用 OCR 取文本（比 UIA 读控件更耐受版本变化）
3. **剪贴板发送**：写剪贴板 + Ctrl+V，绕开中文 IME
4. **轮询取新消息**：微信没有事件机制，只能定时快照 + diff
5. **版本适配层**：把"控件选择器"抽成配置文件，微信升级只改配置不改代码

这一项的投入产出比最差，建议放在最后做，或者直接用企业微信 API 替代。

---

## 四、怎么"知道当前画面反馈" —— 四种手段按可靠性排序

### ① 语义断言（最可靠，优先用）

不要 `sleep(2)` 然后假设完成。改成"等某个语义条件成立":

```python
def wait_until(check, timeout=10, interval=0.3):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = check()
        if r:
            return r
        time.sleep(interval)
    return None

# 点击提交后，等"提交成功"这行字出现
ok = wait_until(lambda: find_ctrl(win, "提交成功", "TextControl"))
```

这是我这轮实测用的方式，有效且稳定。

### ② 差异快照（判断"有没有变化"）

```python
before = snapshot(win)          # dict[id] -> (role, name, value)
click(...)
after  = snapshot(win)
added   = after.keys() - before.keys()
removed = before.keys() - after.keys()
changed = {k for k in before.keys() & after.keys() if before[k] != after[k]}
```

新增/消失/变化三个集合，就是 Agent 判断"刚才那步到底干了什么"的依据。

### ③ 事件订阅（低延迟，但工程复杂）

- UIA：`AddStructureChangedEventHandler` / `AddPropertyChangedEventHandler`，需要独立线程跑消息循环
- CDP：`Page.frameNavigated`、`DOM.documentUpdated`、`Network.responseReceived`

适合需要"秒级感知"的系统。第一次做建议先不上，用轮询 + diff 足够。

### ④ 视觉 diff（兜底）

截两张图做像素比对，只用来判断"界面变没变"，不做语义解释。适合完全无法结构化的界面（游戏、远程桌面画面）。

---

## 五、结构化输出的实际格式（实测样例）

这就是 `uia_snapshot.py` 对 Chrome 页面输出的真实结果，304 个原始节点压成 70 行：

```
窗口: Agent 感知测试页 - Google Chrome
原始节点 304 → 过滤后 70 个有语义元素

#33  Text      "订单录入（感知测试）" @(58,137,1169x26)
#36  Edit      "客户名称"            @(158,176,256x28)
#37  Spinner   "订单金额"            @(158,215,256x28)
#38  ComboBox  "所属区域"            @(162,254,241x28)
#39  CheckBox  "加急"                @(162,297,240x14)
#40  Button    "提交订单"            @(58,326,90x34)
#41  Button    "重置"                @(160,326,63x34)
#42  Text      "等待提交…"           @(66,502,78x22)
#47  DataItem  "订单号"              @(58,375,93x35)
#51  DataItem  "SO-1001"             @(58,409,93x35)
#52  DataItem  "杭州云图"            @(150,409,90x35)
```

几点设计要点：
- **编号**用于让模型回指（"点 #40"比"点坐标为 (58,326) 的按钮"稳得多）
- **过滤**只保留可见 + 有语义 + 尺寸有效的节点，压掉 80% 噪音
- **文本节点要全部保留**，它们就是"当前画面反馈"
- 表格按 `DataItem` 保留，行内顺序即列顺序

---

## 六、落地架构：统一感知层，按目标路由

不要为每个应用写一套逻辑。抽一个 `snapshot(target)` 接口，底下按目标类型选 provider：

```python
def snapshot(target):
    kind = detect(target)          # 'wps' | 'browser' | 'electron' | 'native' | 'unknown'

    if kind == 'wps':
        return com_snapshot(target)        # COM 读文档模型，最准
    if kind == 'browser' and target.cdp:
        return cdp_snapshot(target)        # CDP 拿 DOM + AX + 网络状态
    if uia_snapshot(target).quality > THRESHOLD:
        return uia_snapshot(target)        # UIA 树够用就用
    if ocr_can_read(target):
        return ocr_snapshot(target)        # 文字能认出来
    return vision_snapshot(target)         # 最后兜底
```

`quality` 这个判断很关键，建议用：**有效元素数 / 屏幕面积**、**是否包含关键区域文本**、**与上一帧的稳定度**。WPS 那种 160 节点却只有 22 个菜单项的情况，quality 会很低，自动降级到 COM 或视觉。

动作层同理，按优先级选：
`UIA Pattern（Invoke/Value/Toggle）` → `COM/API 调用` → `SendInput` → `PostMessage` → `坐标点击`

---

## 七、留给你的代码

| 文件 | 作用 |
|---|---|
| `tools/uia_snapshot.py` | **核心件**。Win32 枚举窗口 + UIA 附加，输出带编号的语义快照。支持 `--json` 给程序用 |
| `tools/e2e_loop.py` | 端到端闭环范例：找元素 → ValuePattern 赋值 → InvokePattern 触发 → 读回反馈 |
| `tools/test_wps_com.py` | WPS COM 通道验证与用法示范 |
| `tools/probe_uia.py` | 批量统计各窗口的可访问性质量（选型时用） |
| `tools/list_windows.py` | 枚举可见窗口、进程、句柄 |
| `tools/test_page.html` | 测试用页面，含表单 + 表格 + 动态反馈 |

快速上手：

```bash
# 列出所有窗口
python tools/list_windows.py

# 看某个窗口的结构化快照
python tools/uia_snapshot.py "记事本"

# 看 JSON 格式（给代码用）
python tools/uia_snapshot.py "记事本" --json
```

---

## 八、结论

| 问题 | 答案 |
|---|---|
| 能否精准结构化告诉 Agent | **能**，但要按应用类型选通道，不能一条路走到底 |
| WPS 能否精准操控 | **能**，走 COM 读写文档模型；界面操作只能到菜单级，别指望 |
| 浏览器能否精准操控 | **能**，加 `--force-renderer-accessibility` 走 UIA，或直接 CDP（更强） |
| 微信能否精准操控 | **能但脆弱**，UIA + OCR + 剪贴板组合；本机未装，未实测 |
| 能否知道反馈并继续 | **能**，语义断言 + 差异快照，实测闭环通过 |

一句话：**结构化不是"描述屏幕"，是"给每个可操作对象一个稳定身份 + 当前状态"，然后让 Agent 用身份而不是坐标去操作。**

最后提醒两个本机发现、值得写进设计的坑：

1. **UIA 根节点枚举不可靠** —— Chrome 窗口根本不出现在 `GetRootControl()` 的 children 里，但 Win32 枚举得到。必须先 Win32 拿句柄，再 `ControlFromHandle` 附加。我第一次探测就栽在这。
2. **Chromium 的无障碍树是惰性构建的** —— 同一个 Electron 窗口，第一次探测 11 个节点，稍后探测 603 个。设计上要允许"首次感知质量低，重试一次"，别把首帧当真相。
