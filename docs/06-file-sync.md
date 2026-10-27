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

## 三、三个脚本

| 脚本 | 运行在哪 | 作用 |
|---|---|---|
| `scripts/export-bundle.ps1` | Windows | 打包成 `wcu-YYYYMMDD-HHMM.bundle` |
| `scripts/import-bundle.sh` | Mac | 校验 + 拉取 + 安全快进 |
| `scripts/watch-inbox.sh` | Mac | 监视 `~/wcu-inbox`，来文件就自动导入 |

---

## 四、完整流程

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

## 五、Mac 侧改动怎么回传给 Windows

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

## 六、安全设计

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

## 七、已验证 / 未验证

| 项 | 状态 |
|---|---|
| `export-bundle.ps1` 生成的 bundle 被 git 正确识别 | ✅ 已验证（169 KB，含全部历史） |
| `import-bundle.sh` 正常快进 | ✅ 已验证（新增提交被正确快进，新增文件落盘） |
| 本地有未提交改动时拒绝覆盖 | ✅ 已验证（返回码 4，本地改动完整保留） |
| `watch-inbox.sh` 自动导入 | ⚠️ 逻辑简单，未做长时间挂机测试 |
| `export-bundle.ps1` 在真 Windows 上运行 | ❌ 未验证，本机是 Mac，PowerShell 参数未实跑 |

---

## 八、注意事项

1. **bundle 用 `--all` 打包**，否则只打当前分支，Windows 上新建的分支会丢。
2. **不要用 bundle 传超大二进制**。这个仓库 169 KB 没问题，但如果以后塞进模型权重、
   截图集，bundle 会等比例膨胀（它不做 zip 那种高压缩，只是 git 打包）。那时该换 LFS 或网盘。
3. **两边都改同一文件**时，`--ff-only` 会拒绝。这是刻意的——宁可让你手动处理，
   也不要静默覆盖。手动方案：`git pull --rebase winsrc master`。
4. **bundle 文件本身别提交进仓库**。`.gitignore` 里加 `*.bundle`。
