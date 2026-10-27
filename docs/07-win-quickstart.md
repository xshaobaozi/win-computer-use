# Windows 侧速查

> 这份是给公司电脑看的。Mac 侧已经配好，仓库在 `/Users/pengyijun/kingsoft/win-computer-use`。

---

## 一、拿到项目：三选一

### 方案 1：从 Mac 直接克隆（需要 SSH 通）

前提：Mac 已开「远程登录」，公钥已加进 Mac 的 `~/.ssh/authorized_keys`。

```powershell
git clone ssh://pengyijun@10.13.230.174/Users/pengyijun/repos/win-computer-use.git
```

### 方案 2：从 GitHub 克隆（公司网络能上 GitHub 时）

```powershell
git clone https://github.com/xshaobaozi/win-computer-use.git
```

### 方案 3：从 bundle 离线引导（**网络完全不通时用这个**）

这条路不需要任何网络，只要能把一个文件传过来。

Mac 上先生成一个全量 bundle：

```bash
cd /Users/pengyijun/kingsoft/win-computer-use
git bundle create /tmp/win-bootstrap.bundle master
```

把 `win-bootstrap.bundle` 用微信发到公司电脑，然后：

```powershell
# 直接把 bundle 当仓库克隆（bundle 支持被 clone）
git clone C:\Users\Kingsoft\Downloads\win-bootstrap.bundle win-computer-use
cd win-computer-use
git log --oneline -1          # 应该看到和 Mac 一样的提交
```

这样拿到的仓库历史完整，之后就能正常 commit。

---

## 二、装依赖

```powershell
cd win-computer-use
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt -r requirements-agent.txt
```

`requirements.txt` 里的 `pywin32` / `uiautomation` 只有 Windows 才装得上，Mac 那边装不了，这是正常的。

---

## 三、改完代码，怎么同步回 Mac

**先确认在 master 上**（脚本只认 master，别的分支会拒绝）：

```powershell
git branch --show-current      # 必须输出 master
```

### 方式 A：打 bundle，用微信传（零网络，最稳）

```powershell
.\scripts\export-bundle.ps1
```

会生成 `wcu-20261027-1615.bundle`，用微信发给 Mac 上的自己，
Mac 把文件放进 `~/wcu-inbox/` 即可（如果 Mac 上跑着 `watch-inbox.sh` 会自动导入）。

### 方式 B：Mac 开了同步服务时，一条命令

```powershell
# Mac 上先跑: python3 scripts/sync-server.py --host 0.0.0.0 --token 你的口令
.\scripts\sync.ps1 -Push -Server http://10.13.230.174:8766 -Token 你的口令
```

### 方式 C：SSH 通了的话，直接推

```powershell
git push origin master
```

Mac 那边中枢仓库的钩子会自动快进工作副本，你不用管。

---

## 四、把 Mac 的改动拉下来

```powershell
# 已配 origin 指向 Mac 时
git pull --rebase origin master

# 或者让 Mac 打包，你这边导入
git fetch D:\wcu-from-mac.bundle "refs/heads/master:refs/remotes/macsync/master"
git merge --ff-only macsync/master
```

---

## 五、提交前自检（重要）

```powershell
git branch --show-current    # 必须是 master
git status                   # 确认没有意外的未提交文件
```

`export-bundle.ps1` 和 `sync.ps1` 都会检查分支，不在 master 上会直接报错退出（返回码 10）。
这是刻意的：**只同步 master**，避免两台机器出现「某个分支只在一边存在」的状态。

---

## 六、别做的事

| 别做 | 为什么 |
|---|---|
| 在 feature 分支上直接打包同步 | 脚本会拒绝；而且 bundle 只带 master，那个分支的提交会丢 |
| 两端同时改同一个文件的同一处 | 会触发 `--ff-only` 拒绝合并，得手动 rebase |
| 把 `.bundle` 提交进仓库 | `.gitignore` 已排除，但还是别手动加 |
| 用 zip 代替 bundle | zip 丢历史，只能整包覆盖成快照提交 |
