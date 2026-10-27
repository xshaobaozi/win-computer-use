# 局域网 Git 中枢：把 Mac 当 git 服务用

> 适用场景：公司电脑连不上 VPN / GitHub，但两台机器在同一局域网。
> 做法：Mac 上开一个裸仓库当"私有 git 服务"，公司电脑直接 `push` 到它，
> 完全不碰外网。Mac 再决定何时把代码同步到 GitHub。

---

## 一、为什么不用"共享代理"

把 Mac 的代理开放给局域网（Clash 的 Allow LAN）技术上可行，但：

- 代理端口一旦绑 `0.0.0.0`，**同网段任何人都能用你的节点**，包括公司 IT 的扫描
- 公司网络里私自架设代理出口，多数有合规风险
- 排查泄漏时，出口 IP 指向你的机器

Git 中枢这条路不需要暴露任何代理，走 SSH 密钥认证，流量只在你两台机器之间。

---

## 二、拓扑

```
公司 Windows                Mac (10.13.230.174)                    GitHub
    |                              |                                 |
    |  git push (SSH, 局域网)       |                                 |
    +----------------------------->| ~/repos/win-computer-use.git    |
                                   |        |                        |
                                   |        | post-receive 钩子      |
                                   |        v                        |
                                   | 工作副本自动快进                  |
                                   |                                 |
                                   |  git push origin (走 127.0.0.1:12334 代理)
                                   +-------------------------------->|
```

关键点：**公司电脑完全不需要访问外网**。它只需要能 SSH 到这台 Mac。

---

## 三、Mac 侧：已经配好的部分

| 项 | 值 |
|---|---|
| 裸仓库 | `~/repos/win-computer-use.git` |
| 默认分支 | `master`，当前 `a8acbb1` |
| 钩子 | `hooks/post-receive`，收到推送后自动快进工作副本 |
| 日志 | `~/repos/hub.log` |
| 工作副本 remote | `hub` → 指向该裸仓库 |

钩子的安全边界：**只做 fast-forward**。工作副本有未提交改动、或已分叉、
或当前不在 `master` 分支时，只打印提示，绝不强行覆盖。

---

## 四、Mac 侧：还差一步，需要你手动操作

```bash
# 方式一：图形界面
#   系统设置 → 通用 → 共享 → 打开「远程登录」

# 方式二：终端（要输密码）
sudo systemsetup -setremotelogin on
```

验证（应该看到 sshd 在 22 端口监听）：

```bash
lsof -nP -iTCP:22 -sTCP:LISTEN
```

没开的话，公司电脑连过来会报 `Connection refused`。

---

## 五、Windows 侧配置

### 1. 准备 SSH 密钥

Windows 10/11 自带 OpenSSH 客户端，不需要装东西。PowerShell 里：

```powershell
ssh-keygen -t ed25519 -C "company-pc"
type $env:USERPROFILE\.ssh\id_ed25519.pub
```

把输出的那一行公钥发给 Mac（微信/邮件都行），在 Mac 上执行：

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
echo 'restrict,command="/usr/bin/git-shell -c \"$SSH_ORIGINAL_COMMAND\"" ssh-ed25519 AAAA...你的公钥... company-pc' >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

⚠️ **注意行首那两个限制项不要漏掉**（`restrict` 和 `command=`），它们的作用见第八节。
漏掉的话这把钥匙就等于整机 shell 权限。

### 2. 先验证能不能连

```powershell
ssh pengyijun@10.13.230.174 "cd ~/repos/win-computer-use.git && git log --oneline -1"
```

返回 `a8acbb1 feat: 拆分 ...` 就通了。

### 3. 克隆（不用 GitHub）

```powershell
git clone ssh://pengyijun@10.13.230.174/Users/pengyijun/repos/win-computer-use.git
cd win-computer-use
git config user.name "你的名字"
git config user.email "你的邮箱"
```

克隆下来 `origin` 就指向这台 Mac，日常照常用 `git push` / `git pull`。

### 4. 可选：把 GitHub 加成二级远端

等 Mac 那边把代码推到 GitHub 后，公司电脑网络正常时也能对齐：

```powershell
git remote add github git@github-proxy:xshaobaozi/win-computer-use.git
git fetch github
```

平时不必用，`origin`（Mac）已经够。

---

## 六、日常流程

```
公司电脑:  改代码 → git commit → git push
Mac:       ——什么都不用做，钩子自动快进——
Mac:       git push origin master     （走代理推到 GitHub，可选）
```

反向（Mac 改完给公司电脑）需要手动拉一次：

```bash
# Mac
cd ~/WorkBuddy/2026-10-27-10-25-34/win-computer-use
git push hub master
```

```powershell
# 公司电脑
git pull
```

---

## 七、注意事项

1. **IP 会变**。`10.13.230.174` 是 DHCP 分的，换网络或续租后可能变。
   查当前 IP：`ipconfig getifaddr en0`。建议在路由器上给 Mac 绑个 DHCP 保留地址。
2. **只在一个方向改**。避免 Mac 和公司电脑同时改同一个文件——虽然没有远端冲突，
   但钩子做 ff 失败时会跳过合并，容易让人误以为同步了。以公司电脑为主力开发机，
   Mac 只做查看和小修。
3. **这是公司网络里的一个 SSH 服务**。如果你司对入站端口有审计，22 端口长开
   可能被注意到。不用的时候建议关掉「远程登录」。
4. 裸仓库不要放进工作目录，也不要被任何工具自动清理——它是同步的唯一枢纽。

---

## 八、安全边界（必读）

### 8.1 已实施：把密钥关进 git 一个笼子里

`authorized_keys` 里这一行：

```
restrict,command="/usr/bin/git-shell -c \"$SSH_ORIGINAL_COMMAND\"" ssh-ed25519 AAAA... company-pc
```

两个限制项的含义：

| 项 | 作用 |
|---|---|
| `restrict` | 关掉端口转发、agent 转发、X11 转发、PTY、用户 rc 脚本 |
| `command="git-shell -c ..."` | 强制所有登录都跑 `git-shell`，它只认 `git-upload-pack` / `git-receive-pack` |

**实测效果**（直接在 Mac 上模拟 sshd 的调用）：

```
$ SSH_ORIGINAL_COMMAND="git-upload-pack '/Users/.../win-computer-use.git'"  →  正常返回 refs，clone 可用
$ SSH_ORIGINAL_COMMAND="cat /etc/passwd"                                   →  fatal: unrecognized command
$ SSH_ORIGINAL_COMMAND=""                                                  →  fatal: unrecognized command
```

也就是说：**这把钥匙拿到手，也只能读写这一个仓库，拿不到 shell，不能当跳板，不能转发端口。**
这把钥匙落在公司电脑上（哪怕私钥没设密码）最坏情况是有人能改这个仓库的代码——而不是接管你的 Mac。

### 8.2 仍然存在的风险

| 风险 | 严重度 | 说明与缓解 |
|---|---|---|
| **公司合规** | 高 | 这才是最大的风险，不是技术问题。在公司网内开入站 SSH 服务、绕开网络管控，可能被视为私设服务。缓解：只用它传代码，绝不当代理跳板；不用时关掉远程登录；不碰公司数据。 |
| **22 端口可能被审计** | 中 | 公司 IT 可能扫描入站端口。缓解：需要时开、用完关；或改非标准端口（降低噪音，不替代认证）。 |
| **密码登录未禁用** | 中 | macOS 的 sshd 默认仍允许密码登录，同网段可暴力破解你的 Mac 账户。缓解：见 8.3。 |
| **私钥无 passphrase** | 低（已缓解） | 你的密钥是空密码。因为有 git-shell 限制，风险被压到"仅这个仓库"。但若哪天把限制去掉，风险立刻变高。 |
| **仓库内容** | 低 | 这是公开仓库，没有敏感数据。如果以后放进公司代码或密钥，风险等级要重新评估。 |

### 8.3 建议补上的两步（需要你自己输密码）

**一、禁用 SSH 密码登录**，只留公钥：

```bash
sudo cp /etc/ssh/sshd_config /etc/ssh/sshd_config.bak
sudo sed -i '' 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo sed -i '' 's/^#*KbdInteractiveAuthentication.*/KbdInteractiveAuthentication no/' /etc/ssh/sshd_config

# 验证：应输出 passwordauthentication no
sudo sshd -T | grep -E "passwordauthentication|kbdinteractive"
```

改完不需要重启，下次连接即生效。

> 如果这两行在文件里本来是被注释掉的（`#PasswordAuthentication yes`），
> sed 会把它替换掉；如果完全不存在，需要手动往文件里加一行 `PasswordAuthentication no`。

**二、给私钥加 passphrase**（在公司电脑上）：

```powershell
ssh-keygen -p -f $env:USERPROFILE\.ssh\id_ed25519
```

加完之后每次用到会提示输入，可以配合 Windows 的 OpenSSH Authentication Agent 记住。

**三、不用时关掉**。远程登录开关在「系统设置 → 通用 → 共享」，随手关掉就没有暴露面了。

### 8.4 想彻底不暴露端口？用反向隧道

如果公司网络策略很严，可以反过来：**由 Mac 主动连出去**，不在 Mac 上开任何入站端口。

这种方式需要一台双方都能访问的中转（比如你家里那台常开的设备，或一个便宜的 VPS），
本质是 `ssh -R` 反向端口转发。缺点是要多一个中间人，当前场景收益不大——除非公司明确禁止入站端口。

---

## 九、IP 会变怎么办

`10.13.230.174` 是 DHCP 分的，换网、续租、休眠后重连都可能变。三个办法，按推荐度排序：

### 9.1 路由器绑定 DHCP 保留地址（最可靠）

进 Ruijie 后台，找到 Mac 的 MAC 地址，绑定一个固定 IP。一次配置永久有效。

### 9.2 试一下 mDNS 主机名

Mac 的主机名是 `pengyijundemacbook-air`，理论上可以用 `.local` 名字访问：

```powershell
ping pengyijundemacbook-air.local
ssh pengyijun@pengyijundemacbook-air.local "echo OK"
```

Windows 10/11 自带 mDNS 解析，但**不一定对所有场景生效**（有时需要装 Bonjour）。
如果 ping 得通，那就再也不怕 IP 变了，优先用这个名字。

### 9.3 给 SSH 配别名，只改一个地方（兜底）

在公司电脑上建 `C:\Users\Kingsoft\.ssh\config`：

```
Host mac
    HostName 10.13.230.174
    User pengyijun
    IdentityFile ~/.ssh/id_ed25519
    ServerAliveInterval 30
```

之后所有命令都用别名，IP 变了只改这一行：

```powershell
ssh mac "echo OK"
git clone mac:/Users/pengyijun/repos/win-computer-use.git
```

注意 `git clone mac:...` 用的是 scp 风格路径，冒号后面直接跟绝对路径，不需要 `ssh://`。
已有的仓库改远端：`git remote set-url origin mac:/Users/pengyijun/repos/win-computer-use.git`

---

## 十、已验证 / 未验证

| 项 | 状态 |
|---|---|
| 裸仓库创建、推送初始提交 | ✅ 已验证 |
| `post-receive` 自动快进工作副本 | ✅ 已验证（模拟推送 `09a80d0` / `b92f8ce` 均正确快进） |
| 钩子对本地改动的保护（拒绝非 ff） | ✅ 代码逻辑已实现，未构造冲突场景实测 |
| 公钥指纹与 Win 侧一致 | ✅ 已验证（`SHA256:6tvhp+cK2cZniEDm4yy4DafHz+7OaTKv6P8O8KD0tgA`） |
| `restrict` + `git-shell` 限制生效 | ✅ 已验证（git 命令通过，`cat /etc/passwd` 与空命令均被拒） |
| SSH 连通性（公司电脑 → Mac） | ❌ 未验证，远程登录尚未开启 |
| 禁用密码登录 | ❌ 未执行，需要 sudo |

---

## 十一、排错

| 现象 | 原因 | 处理 |
|---|---|---|
| `Connection refused` | 远程登录没开 | 打开「共享 → 远程登录」 |
| `Permission denied (publickey)` | 公钥没加或权限不对 | 检查 `~/.ssh/authorized_keys` 内容与 `600` 权限 |
| 推上去了但 Mac 文件没变 | 工作副本有本地改动 | 看 `~/repos/hub.log`，手动 `git pull --rebase hub master` |
| `fetch 失败` | 工作副本缺 `hub` 远端 | `git remote add hub ~/repos/win-computer-use.git` |
| 推送很慢或超时 | 两台机器不在同一子网 | `ping 10.13.230.174` 确认，或检查公司是否开了客户端隔离 |

---

## 十二、备选：如果开不了远程登录

Mac 上（不需要管理员权限）：

```bash
git daemon --base-path=$HOME/repos --export-all --enable=receive-pack \
  --reuseaddr --informative-errors --verbose /Users/pengyijun/repos/win-computer-use.git
```

公司电脑：

```powershell
git clone git://10.13.230.174/win-computer-use.git
```

**但这没有认证**，同网段任何人都能读写这个仓库。只在你确认局域网可信、且能接受
风险时使用，用完立刻停掉。优先选 SSH。
