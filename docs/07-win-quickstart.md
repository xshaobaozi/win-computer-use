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
git bundle create /tmp/win-bootstrap.bundle HEAD master
```

⚠️ **注意 `HEAD` 不能省**。只写 `master` 的话 bundle 里没有 HEAD 引用，
对方 `git clone` 会去找不存在的 `main` 分支，结果是**检出空目录**并报
`warning: remote HEAD refers to nonexistent ref`。

把 `win-bootstrap.bundle` 用微信发到公司电脑，然后在**目标目录里**执行下面这套。
它比 `git clone` 更稳，因为：不要求目录是空的，也不要求 bundle 里带 HEAD。

```bash
cd /c/c-kingsoft

# 0. 先确认目录里那个意外的 .git 没有提交（有提交就别删，先备份）
git log --oneline 2>&1 | head -3
ls -A

# 1. 删掉意外的空仓库，重新初始化到 master
rm -rf .git
git init -b master

# 2. 从 bundle 取回全部历史和工作区
git fetch ~/Downloads/win-bootstrap.bundle master
git reset --hard FETCH_HEAD

# 3. 确认
git log --oneline -1        # 应显示和 Mac 一样的提交
ls
```

`git init -b master` 需要 git ≥ 2.28。老版本用：

```bash
git init
git symbolic-ref HEAD refs/heads/master
```

如果目录里还有别的杂物，`git reset --hard` **不会删它们**，只会显示成未跟踪文件
（`git status` 里是 `??`），可以事后手动清理。

#### 如果你就是想用 clone

如果 `C:\c-kingsoft` 确实是空的，那也可以直接克隆：

```bash
git clone ~/Downloads/win-bootstrap.bundle /c/c-kingsoft
```

但要注意：**目录非空会失败**，而且用不带 HEAD 的旧 bundle 克隆会得到空目录，
此时补一条 `git checkout master`。

---

## 一之二、克隆完成后 origin 指向的是那个 bundle 文件

```powershell
git remote -v
# origin  C:\Users\Kingsoft\Downloads\win-bootstrap.bundle (fetch)
# origin  C:\Users\Kingsoft\Downloads\win-bootstrap.bundle (push)
```

这是正常的——origin 指向本地文件，**不能 push**。后续同步用第三节的
「打包 → 传 → 导入」流程，或者等 SSH 打通了再挂一个真正的远端：

```powershell
git remote add mac ssh://pengyijun@10.13.230.174/Users/pengyijun/repos/win-computer-use.git
git push mac master
```

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
