# win-computer-use

Windows 电脑操控 Agent 的感知与执行层：**看懂屏幕、结构化界面、精准操作**，并支持由局域网内另一台机器的 Agent 远程驱动。

这个仓库是一轮完整技术验证的产物——所有结论都来自本机实测，不是纸面推演。

---

## 三条核心结论

**1. 屏幕识别是"分级路由"问题，不是单一算法。**

```
UIA 控件树（最准最省） → OCR / 模板匹配（兜底文字） → 视觉模型（最后防线）
```

任何一层单独用都不够。生产系统必须按目标应用的实际情况自动降级。

**2. 不同应用该走完全不同的通道。**

| 应用类型 | 通道 | 原因 |
|---|---|---|
| WPS / Office 文档 | **COM 接口** | 直接操作文档模型，不看屏幕、不受版本影响 |
| 浏览器 | **UIA + `--force-renderer-accessibility`**，或 **CDP** | 默认不暴露网页内容 |
| CEF / Electron 内嵌界面 | **OCR** | 无障碍树完全为空，只能读像素 |
| 原生 Win32 / WPF | **UIA** | 语义完整、坐标精确 |

**3. 能"读"不等于能"点"。**

权限边界必须先确认：无输入桌面权限时，`SetCursorPos` / `SendInput` 全部失效，而 UIA 的 `InvokePattern` 依然可用。这个差异决定了架构怎么设计。

---

## 实测数据速览

统一口径：`原始控件节点数 → 过滤后的有效元素数`

| 应用 | 原始节点 | 有效元素 | 内容可读 | 可用通道 |
|---|---|---|---|---|
| Chrome（默认启动） | 235 | 25 | ❌ 网页 0 命中 | — |
| Chrome（加无障碍 flag） | 304 | 70 | ✅ 表单/表格全在 | UIA / CDP |
| WPS 首页 | 135 | 12 | ❌ | UIA（按钮）/ OCR |
| WPS 文档窗口 | 160 | 22 | ❌ 正文不可读 | **COM** |
| WPS 登录窗（CEF） | 16 | 4 | ❌ | **仅 OCR** |
| Electron 应用 | 603 | 176 | ✅（取决于应用） | CDP |

详见 [docs/02-screen-structuring-report.md](docs/02-screen-structuring-report.md)。

---

## 目录结构

```
win-computer-use/
├── docs/
│   ├── 01-remote-agent-architecture.md    局域网双机操控架构设计
│   ├── 02-screen-structuring-report.md    屏幕结构化 + 闭环实测报告
│   ├── 03-wps-control-attempts.md         WPS 登录窗七条路径穷举
│   └── assets/
│       └── wps-login-ocr.png              OCR 识别可视化证据
├── tools/
│   ├── uia_snapshot.py       ★ UIA 结构化快照（核心件）
│   ├── vision_snapshot.py    ★ 截图 + OCR 视觉快照
│   ├── annotate.py             识别结果可视化标注
│   ├── e2e_loop.py           ★ 端到端闭环范例
│   ├── test_wps_com.py         WPS COM 通道验证
│   ├── post_click.py           窗口消息点击（无光标权限备选）
│   ├── msaa_probe.py           MSAA / IAccessible 探测
│   ├── cef_probe.py            CEF DevTools 调试端口扫描
│   ├── probe_uia.py            批量评估窗口可访问性质量
│   ├── list_windows.py         枚举窗口 / 进程 / 句柄
│   └── test_page.html          测试用页面（表单 + 表格 + 动态反馈）
├── requirements.txt
└── README.md
```

---

## 快速开始

```bash
# 1. 建环境
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# 2. 看当前有哪些窗口
python tools/list_windows.py

# 3. 读某个窗口的结构化快照
python tools/uia_snapshot.py "记事本"

# 4. 给代码用的 JSON 格式
python tools/uia_snapshot.py "记事本" --json
```

---

## 脚本清单

| 脚本 | 用途 | 命令示例 |
|---|---|---|
| `uia_snapshot.py` | UIA 树 → 带编号的元素表 | `python tools/uia_snapshot.py "标题"` |
| `vision_snapshot.py` | 截图 + OCR → 带坐标元素表 | `python tools/vision_snapshot.py "标题" --click "按钮文字"` |
| `annotate.py` | 把识别结果画回截图 | `python tools/annotate.py "标题" "目标文字"` |
| `e2e_loop.py` | 感知→赋值→触发→读反馈 | `python tools/e2e_loop.py` |
| `test_wps_com.py` | WPS COM 建/写/读/格式化 | `python tools/test_wps_com.py` |
| `post_click.py` | 不经过光标的窗口消息点击 | `python tools/post_click.py "标题" "目标"` |
| `msaa_probe.py` | 检查 IAccessible 是否有内容 | `python tools/msaa_probe.py` |
| `cef_probe.py` | 扫描 CEF 调试端口 | `python tools/cef_probe.py` |
| `probe_uia.py` | 批量评估各窗口质量 | `python tools/probe_uia.py` |

---

## 关键坑（都踩过）

1. **UIA 根节点枚举不可靠** — Chrome 窗口不出现在 `GetRootControl()` 的 children 里，但 Win32 枚举得到。必须先 `EnumWindows` 拿句柄，再 `ControlFromHandle` 附加。
2. **`BoundingRectangle.width` 是方法不是属性** — 要用 `right - left`。
3. **Chromium 无障碍树惰性构建** — 同一窗口首次探测 11 个节点，稍后 603 个。首帧不可信。
4. **CEF 窗口 `PrintWindow` 可能全白** — 未渲染完成时抓出来是纯色，必须先检查灰度范围再 OCR。
5. **DPI 缩放** — 进程必须声明 PerMonitorV2，坐标统一在物理像素空间算。
6. **UIPI 隔离** — 管理员权限运行的窗口，非提权进程读不到、点不了。
7. **Windows 服务看不到桌面** — 感知服务必须是交互式用户进程，不能做成 Session 0 服务。

---

## 文档索引

| 文档 | 内容 |
|---|---|
| [01 远程操控架构](docs/01-remote-agent-architecture.md) | 局域网双机方案、协议设计、带宽与安全、开源方案盘点 |
| [02 屏幕结构化](docs/02-screen-structuring-report.md) | 四视图模型、各应用实测数据、反馈闭环四种手段 |
| [03 WPS 七条路径](docs/03-wps-control-attempts.md) | UIA / MSAA / CDP / 参数注入 / OCR / 鼠标 / 消息，逐条实测结果 |

---

## 环境

- Windows 10 / 11
- Python 3.10+（实测 3.13）
- 依赖见 `requirements.txt`；OCR 用 `rapidocr-onnxruntime`，离线、无需额外二进制
