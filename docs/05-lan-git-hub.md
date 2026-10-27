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
echo 'ssh-ed25519 AAAA...你的公钥... company-pc' >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

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

## 八、已验证 / 未验证

| 项 | 状态 |
|---|---|
| 裸仓库创建、推送初始提交 | ✅ 已验证 |
| `post-receive` 自动快进工作副本 | ✅ 已验证（模拟推送 `09a80d0` / `b92f8ce` 均正确快进） |
| 钩子对本地改动的保护（拒绝非 ff） | ✅ 代码逻辑已实现，未构造冲突场景实测 |
| SSH 连通性（公司电脑 → Mac） | ❌ 未验证，远程登录尚未开启 |

---

## 九、排错

| 现象 | 原因 | 处理 |
|---|---|---|
| `Connection refused` | 远程登录没开 | 打开「共享 → 远程登录」 |
| `Permission denied (publickey)` | 公钥没加或权限不对 | 检查 `~/.ssh/authorized_keys` 内容与 `600` 权限 |
| 推上去了但 Mac 文件没变 | 工作副本有本地改动 | 看 `~/repos/hub.log`，手动 `git pull --rebase hub master` |
| `fetch 失败` | 工作副本缺 `hub` 远端 | `git remote add hub ~/repos/win-computer-use.git` |
| 推送很慢或超时 | 两台机器不在同一子网 | `ping 10.13.230.174` 确认，或检查公司是否开了客户端隔离 |

---

## 十、备选：如果开不了远程登录

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
