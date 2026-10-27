# 文件同步方案：bundle + 任意传输通道

> 适用场景：公司电脑既连不上 GitHub，也不方便开 SSH 服务。
> 做法：把仓库打成**单个 bundle 文件**，用任何方式传过来，Mac 端一条命令合并。

**核心优势：Mac 上不开放任何入站端口，不装任何服务，纯文件搬运。**
合规风险从"架了个服务"降到"两个文件"。

---

## 一、先说结论：为什么不是 zip

| 方式 | 保留 git 历史 | 能否安全合并 | 冲突处理 | 体积 |
|---|---|---|---|---|
| **git bundle** | ✅ 完整 | ✅ fast-forward | ✅ 有据可依 | 169 KB |
| zip 压缩包 | ❌ 全丢 | ❌ 只能整体覆盖 | ❌ 谁覆盖谁，无法追溯 | 略小 |

zip 的本质是"用新文件替换旧文件"。一旦两边都改过东西，
你唯一能做的就是选一边覆盖另一边，改了什么、丢了什么，全靠猜。

bundle 是 git 官方的离线传输格式，`git bundle create --all` 打出来的文件
可以直接 `git fetch`，等于把远端仓库装进一个文件里。实测这个仓库打成 bundle 是 **169 KB**。

---

## 二、为什么不建议走 whistle / Charles 传文件

这两个是**抓包调试代理**，不是文件服务：

1. **8899 暴露到局域网，风险比开 SSH 更大**。别人连上你的 whistle，等于获得了
   拦截、篡改你所有 HTTP 流量的能力，而不只是读写一个仓库。
2. 传二进制文件不是它们的用途。whistle 的 Values / 临时文件功能是给文本响应体用的，
   塞 169 KB 的二进制会很难受，还要处理编码。
3. 抓包代理会记录完整请求内容，公司流量审计时反而是最显眼的那个。

如果只是想要"能传文件"，`python -m http.server` 更直接，见第四节方案 A。

---

## 三、脚本清单

| 脚本 | 运行在哪 | 作用 |
|---|---|---|
| `scripts/export-bundle.ps1` | Windows | 打包成 `wcu-YYYYMMDD-HHMM.bundle` |
| `scripts/import-bundle.sh` | Mac | 校验 + 拉取 + 安全快进 |
| `scripts/watch-inbox.sh` | Mac | 监视 `~/wcu-inbox`，来文件就自动导入（.bundle / .zip 都认） |
| `scripts/import-zip.sh` | Mac | 导入 zip 快照，只提交本次导入的文件 |
| `scripts/sync-server.py` | Mac | 可选：HTTP 服务，让 Windows 直接推/拉 |
| `scripts/sync.ps1` | Windows | 配合上面，一条命令 `-Push` / `-Pull` |

---

## 四、分支策略（重要）

**只同步 `master`，其他分支一律拒绝。** 这条规则写死进了每一个脚本：

| 位置 | 行为 |
|---|---|
| `export-bundle.ps1` / `sync.ps1 -Push` | 不在 master 上直接报错退出（返回码 10） |
| 打包命令 | 用 `git bundle create x master`，**不是 `--all`** |
| `import-bundle.sh` / `import-zip.sh` | 当前不在 master 上直接拒绝（返回码 10） |
| `import-bundle.sh` 取 ref | 只 fetch `refs/heads/master`，其他分支根本不进来 |
| `sync-server.py` 的 `/bundle` | Mac 不在 master 时返回 409 |

为什么不用 `--all`：它会把 Windows 上的临时分支、实验分支一并带过来，
于是出现「某个分支只在一台机器上存在」的半同步状态——你不知道该以哪台为准。
只打 master 之后，分支层面就不可能冲突。

**注意：限制分支不能消除内容冲突。** 两边都在 master 上改同一个文件的同一行，
仍然是冲突，只是冲突发生在文件内容层面，而 `--ff-only` 会拦住它并让你手动处理。

实测：一个含 `master` + `test-x` 两个分支的 `--all` bundle，
导入后 Mac 上只产生 `winsrc/master`，`test-x` 没有进来。

---

## 五、可选：让 Windows 直接推/拉（HTTP 服务模式）

如果不想每次「打包 → 微信传 → Mac 导入」，可以让 Mac 开一个小服务。

**Mac 侧：**

```bash
python3 scripts/sync-server.py --host 0.0.0.0 --token 你的口令
# 默认只绑 127.0.0.1，--host 0.0.0.0 才供局域网访问
# 不填 --token 会自动生成一个并打印出来
```

**Windows 侧：**

```powershell
# 推：打包 + 上传到 Mac 的 inbox
.\scripts\sync.ps1 -Push -Server http://10.13.230.174:8766 -Token 你的口令

# 拉：从 Mac 下载最新，校验后快进
.\scripts\sync.ps1 -Pull -Server http://10.13.230.174:8766 -Token 你的口令
```

服务端三个端点：

| 端点 | 用途 |
|---|---|
| `GET /health?token=` | 探活，返回当前 HEAD、分支、是否有未提交改动 |
| `GET /bundle?token=` | 现场打包 master 并下载（Windows 用来拉） |
| `POST /upload?name=x.bundle&token=` | 上传 bundle 或 zip 到 inbox（Windows 用来推） |

安全设计：

- **token 必填**，无 token 一律 401
- **只接受 `.bundle` / `.zip`**，传 `.exe` 之类直接 400 —— 不把它变成通用文件服务器
- 默认绑 `127.0.0.1`，绑 `0.0.0.0` 时启动横幅会告警
- 上传只是落盘到 `~/wcu-inbox`，**不直接改工作副本**；合并交给 import 脚本，
  这样「传输」和「合并」解耦，合并失败不会污染仓库
- 上限 200 MB

用完记得 Ctrl-C。长期挂着等于在局域网里常驻一个可写入口。

---

## 六、zip 是怎么处理的

如果 Windows 那边只给了 zip（比如直接右键压缩了整个文件夹），
`import-zip.sh` 会这样处理：

1. 解压到临时目录；如果只有一个顶层文件夹，自动剥掉这一层
2. 如果发现里面带 `.git` 目录，**中止并提示改用 bundle**（那说明整个仓库被压缩了）
3. 排除 `.git`，把文件覆盖到工作副本
4. **只 `git add` 本次导入的那些文件**，然后自动提交一个
   `sync: 导入 Windows zip 快照 (时间)` 的 commit

第 4 步是关键：早期版本用了 `git add -A`，会把工作区里其他未提交的改动
一起卷进这个提交，事后完全解释不清。现在只 add 导入清单里的路径。

zip 的代价是丢历史，所以每个 zip 只能变成一个「快照提交」。
能拿到 bundle 就别用 zip。

---

## 七、完整流程

### 方案 A：临时 HTTP（两台机器都在局域网时最省事）

**Windows 侧：**

```powershell
cd C:\Users\Kingsoft\win-computer-use
.\scripts\export-bundle.ps1
# 输出会告诉你文件路径和本机 IP

# 在 bundle 所在目录起一个临时 HTTP 服务
cd ..
python -m http.server 8000
```

**Mac 侧：**

```bash
cd ~/WorkBuddy/2026-10-27-10-25-34/win-computer-use
curl -O http://<Win的IP>:8000/wcu-20261027-1530.bundle
./scripts/import-bundle.sh wcu-20261027-1530.bundle
```

注意方向：**是 Mac 主动去拉，不是 Win 推过来**。
这样 Mac 一个端口都不用开，公司电脑也只是临时起了个只读 HTTP 服务，用完 Ctrl-C 就没了。

> 反过来让 Win 往 Mac 传，需要 Mac 上跑一个能接受上传的服务
> （`python -m http.server` 不支持 POST 上传），多一层麻烦，没必要。

### 方案 B：微信 / 网盘 / U 盘

```powershell
# Windows 只做打包
.\scripts\export-bundle.ps1
```

把 bundle 文件通过微信「文件传输助手」发给自己，Mac 上保存到 `~/wcu-inbox/`，
然后：

```bash
./scripts/import-bundle.sh ~/wcu-inbox/wcu-20261027-1530.bundle
```

**这条路径零网络配置**，什么都不用开。169 KB 的文件发微信毫无压力。

### 方案 C：全自动（推荐日常用）

Mac 上开一个窗口：

```bash
./scripts/watch-inbox.sh
```

之后你就只需要把 bundle 丢进 `~/wcu-inbox/`（微信下载目录软链接过去也行），
脚本会自动导入、自动快进、处理完移到 `done/`。

---

## 八、Mac 侧改动怎么回传给 Windows

反向是同一个套路，只是 Windows 上没有 import 脚本，用两条 git 命令：

```bash
# Mac 上打包
cd ~/WorkBuddy/2026-10-27-10-25-34/win-computer-use
git bundle create /tmp/wcu-from-mac.bundle --all
```

传到 Windows 后：

```powershell
cd C:\Users\Kingsoft\win-computer-use
git fetch D:\wcu-from-mac.bundle "refs/heads/*:refs/remotes/macsync/*"
git merge --ff-only macsync/master
```

---

## 九、安全设计

`import-bundle.sh` 做了三层保护，每一层都是实测过的：

| 保护 | 行为 |
|---|---|
| **完整性校验** | `git bundle verify` 先跑一遍，缺前置提交或文件损坏直接拒绝，不会导入半个东西 |
| **不直接改 master** | 先 fetch 到 `refs/remotes/winsrc/*`，确认无误才快进 |
| **拒绝覆盖本地改动** | 只做 `--ff-only`，有未提交改动或分叉时**拒绝合并并提示**，不动你的文件 |
| **可回退** | 每次导入都会打印导入前的 commit，出问题一条 `git reset --hard` 回去 |

实测：本地有未提交改动时导入，脚本返回码 4 并明确提示，
本地文件一个字没变，HEAD 也没动。

---

## 十、已验证 / 未验证

| 项 | 状态 |
|---|---|
| `export-bundle.ps1` 生成的 bundle 被 git 正确识别 | ✅ 已验证（169 KB，含全部历史） |
| `import-bundle.sh` 正常快进 | ✅ 已验证（新增提交被正确快进，新增文件落盘） |
| 本地有未提交改动时拒绝覆盖 | ✅ 已验证（返回码 4，本地改动完整保留） |
| `watch-inbox.sh` 自动导入 | ✅ 已验证（放入 bundle 后 7 秒内完成导入，文件落盘、bundle 移入 done/） |
| 非 master 分支拒绝导入 | ✅ 已验证（`test-branch` 上导入 bundle / zip 均返回码 10） |
| 只同步 master，其他分支不进入 | ✅ 已验证（含 `test-x` 的 `--all` bundle 导入后只产生 `winsrc/master`） |
| `sync-server.py` 三个端点 | ✅ 已验证（无 token 401、下载 180 KB 且 bundle 校验通过、上传落盘、`.exe` 被 400 拒绝） |
| `import-zip.sh` 只提交导入文件 | ✅ 已验证（提交里仅 1 个文件，无关的未提交改动未被卷入） |
| `export-bundle.ps1` / `sync.ps1` 在真 Windows 上运行 | ❌ 未验证，本机是 Mac，PowerShell 参数未实跑 |

---

## 十一、注意事项

1. **刻意只打 `master`，不用 `--all`**。所以 Windows 上临时开的实验分支不会传过来——
   这是设计，不是 bug。真要传，先把它合进 master。
2. **不要用 bundle 传超大二进制**。这个仓库 169 KB 没问题，但如果以后塞进模型权重、
   截图集，bundle 会等比例膨胀（它不做 zip 那种高压缩，只是 git 打包）。那时该换 LFS 或网盘。
3. **两边都改同一文件**时，`--ff-only` 会拒绝。这是刻意的——宁可让你手动处理，
   也不要静默覆盖。手动方案：`git pull --rebase winsrc master`。
4. **bundle 文件本身别提交进仓库**。`.gitignore` 里已加 `*.bundle`。
