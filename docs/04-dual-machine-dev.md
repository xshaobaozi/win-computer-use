# 双机开发工作流（Mac + Windows）

> 结论先说：**不需要内网穿透。Git 本身就是同步通道。**
> Mac 负责决策层，Windows 负责感知执行层，两边各自独立开发，靠 push/pull 交换代码。

---

## 一、为什么不需要穿透

穿透解决的是"两台机器的进程要实时通信"。但**开发期**并不需要这个：

| 需求 | 是否需要穿透 | 解法 |
|---|---|---|
| 两边代码互相同步 | ❌ 不需要 | Git 远程仓库（走代理即可） |
| Mac 上开发 agent 逻辑 | ❌ 不需要 | 用 `agent.mock_server` 假数据 |
| Windows 上开发 server | ❌ 不需要 | 本机 `127.0.0.1` 自测 |
| 真机联调（Mac 连 Win 的 WPS） | ✅ 需要同网段 | 回家里局域网，或同办公室局域网 |

也就是说：**只有"最后一公里"的真机联调需要两台机器在一起**，这件事你现在不做。平时各写各的，代码用 Git 对齐。

---

## 二、仓库分层

```
protocol/          ← 双端唯一耦合点，纯标准库，改它等于改两端
  schema.py          消息格式、op 码、坐标空间、错误码
agent/             ← 跨平台，Mac 上开发
  transport.py       WebSocket 客户端（连 mock 或连真 server）
  mock_server.py     假 server，Mac 上独立跑通 agent
  demo.py            端到端闭环示范（感知→定位→执行→校验）
server/            ← 仅 Windows，Win 上开发
  main.py            WS 入口 + op 分发
  perception.py      窗口枚举 / UIA 树 / 截图
  action.py          键鼠注入 / 剪贴板
tools/             ← 原有探针脚本，保持不动，继续当命令行工具用
```

依赖分两份：

- `requirements-agent.txt` — 只有 `websockets`，全平台可装
- `requirements.txt` — 原 Windows 依赖（uiautomation / comtypes / pywin32 …）

---

## 三、日常同步流程

### 关键配置（两台机器各做一次）

```bash
# 让 pull 走 rebase，避免两边交替提交时产生无意义的 merge commit
git config pull.rebase true

# Windows 上建议确认换行符策略（.gitattributes 已声明统一 LF）
git config core.autocrlf false
```

### 每轮开发

```bash
git pull --rebase          # 先拉
# ...改代码...
git add -A && git commit -m "..."
git push
```

**冲突高发区**：`protocol/schema.py`。两边同时改这个文件几乎必然冲突，约定：

- 改协议前先在群里说一声
- 协议改动单独提交，不要混在功能提交里
- 冲突时以"字段只增不改"为原则，破坏性改动必须双端同步发版

---

## 四、Mac 上能做的全部工作

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-agent.txt

# 终端 1：假 server
python -m agent.mock_server
# 终端 2：跑闭环
python -m agent.demo
```

正常输出（`[5]` 出现「已保存」即闭环成立）：

```
[3] 定位目标：保存
    命中 #1 保存  中心点 (813,344)
[4] 执行点击
    server 回执: {'clicked': True, 'hit': '保存'}
[5] 校验：界面真的变了吗
    元素 3 → 4
    新增: 已保存
    ✓ 出现「已保存」，闭环成立
```

在 Mac 上**不能**做：任何 UIA / 截图 / 键鼠注入的真实测试。
`server/` 包在 Mac 上 import 会直接失败（`No module named 'win32api'`），这是刻意设计的守卫，
运行 `python -m server.main` 会打印明确提示而不是抛栈。

---

## 五、Windows 上要做的

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-agent.txt

# 本机自测：server + demo 在同一台机器
python -m server.main                          # 终端 1
python -m agent.demo                           # 终端 2
python -m agent.demo --keyword "WPS"           # 指定窗口关键字
```

### 换到真机联调时（以后回家里局域网）

```powershell
python -m server.main --host 0.0.0.0 --token 你的口令
```

Mac 侧：

```bash
export WCU_TOKEN=你的口令
python -m agent.demo --url ws://<Win的IP>:8765/ws/control
```

`--host 0.0.0.0` 且不设 token 时，server 会主动告警：这个端口的权限等于你的 Windows 账户权限。

---

## 六、Windows 上拉代码（公司电脑首次配置）

Git 访问 GitHub 需要代理，且 **SSH 不认 `http.proxy`**，必须用 ProxyCommand。
在 `C:\Users\<你>\.ssh\config` 里加（假设代理端口 12334）：

```
Host github-proxy
    HostName ssh.github.com
    Port 443
    User git
    IdentityFile ~/.ssh/id_ed25519
    ProxyCommand "C:/Program Files/Git/mingw64/bin/connect.exe" -H 127.0.0.1:12334 %h %p
    ServerAliveInterval 30
```

然后：

```powershell
git clone git@github-proxy:xshaobaozi/win-computer-use.git
```

验证：`ssh -T git@github-proxy` 应返回 `Hi xshaobaozi!`。
Git Bash 自带的 `nc` 不支持 `-X/-x`，所以必须用 Git for Windows 内置的 `connect.exe`。

如果公司网络本来就能直连 GitHub，直接用 `git@github.com:` 即可，不必配代理。

---

## 七、边界约定

1. **`server/` 里只放 Windows 专有代码**，禁止引入任何需要被 agent 复用的逻辑——要复用就往 `protocol/` 或 `agent/` 挪。
2. **`agent/` 里禁止 import Windows 专有包**，包括 `pywin32`、`uiautomation`、`comtypes`。一旦有人加了，Mac 侧立刻跑不起来。
3. **`tools/` 冻结**：那是已验证的探针脚本，作为行为基准保留，不再往里加新东西。
4. 新增 op 时三处同时改：`protocol/schema.py` 的 op 码、`agent/transport.py` 的语法糖、`server/main.py` 的分发。
