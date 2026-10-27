# 在公司电脑上推/拉仓库，配合 Mac 上的 scripts/sync-server.py
#
#   .\scripts\sync.ps1 -Push -Server http://10.13.230.174:8766 -Token abc123
#   .\scripts\sync.ps1 -Pull -Server http://10.13.230.174:8766 -Token abc123
#
# Push: 打包当前仓库 -> 上传到 Mac 的 inbox（不会直接改 Mac 的工作副本）
# Pull: 从 Mac 下载最新 bundle -> 校验 -> 快进本地
#
# 两个动作互相独立。不要指望"双向自动同步"，git 是唯一的仲裁者。

param(
    [switch]$Push,
    [switch]$Pull,
    [string]$Server = "",
    [string]$Token = "",
    [string]$Repo = "."
)

$ErrorActionPreference = "Stop"

if (-not $Push -and -not $Pull) {
    Write-Host "用法:"
    Write-Host "  .\scripts\sync.ps1 -Push -Server http://<Mac的IP>:8766 -Token <口令>"
    Write-Host "  .\scripts\sync.ps1 -Pull -Server http://<Mac的IP>:8766 -Token <口令>"
    exit 1
}
if (-not $Server -or -not $Token) {
    Write-Error "必须同时提供 -Server 和 -Token"
    exit 1
}
$Server = $Server.TrimEnd("/")

$repoFull = (Resolve-Path $Repo).Path
if (-not (Test-Path (Join-Path $repoFull ".git"))) {
    Write-Error "不是 git 仓库: $repoFull"
    exit 1
}

# 分支策略：只同步 master。别的分支一律拒绝，避免两端出现半同步的分支状态。
$SyncBranch = "master"
$current = git -C $repoFull symbolic-ref --short HEAD
if ($current -ne $SyncBranch) {
    Write-Host "✗ 当前分支是 '$current'，同步只允许在 $SyncBranch 上操作。"
    Write-Host "  先切回: git checkout $SyncBranch"
    exit 10
}

$ts = Get-Date -Format "yyyyMMdd-HHmmss"

# ------------------------------------------------------------------ Push
if ($Push) {
    $dirty = git -C $repoFull status --porcelain
    if ($dirty) {
        Write-Host "⚠ 有未提交改动，这些不会进 bundle："
        $dirty | ForEach-Object { Write-Host "    $_" }
        Write-Host ""
    }

    $bundle = Join-Path $env:TEMP "wcu-win-$ts.bundle"
    Write-Host "== 打包 =="
    # 带 HEAD，否则对方 clone 这个 bundle 会检出空目录
    git -C $repoFull bundle create $bundle HEAD $SyncBranch
    if ($LASTEXITCODE -ne 0) { Write-Error "打包失败"; exit 1 }

    $size = [math]::Round((Get-Item $bundle).Length / 1KB, 1)
    $head = git -C $repoFull log --oneline -1
    Write-Host "   $bundle ($size KB)"
    Write-Host "   提交: $head"

    Write-Host ""
    Write-Host "== 上传到 Mac =="
    $uri = "$Server/upload?name=wcu-win-$ts.bundle&token=$Token"
    try {
        $resp = Invoke-WebRequest -Uri $uri -Method Post -InFile $bundle `
            -ContentType "application/octet-stream" -UseBasicParsing -TimeoutSec 120
    } catch {
        Write-Host ""
        Write-Error "上传失败: $($_.Exception.Message)"
        Write-Host "检查: 1) Mac 上服务是否在跑  2) IP/端口对不对  3) token 是否一致"
        exit 2
    }
    Remove-Item $bundle -Force

    $obj = $resp.Content | ConvertFrom-Json
    if ($obj.ok) {
        Write-Host "   ✓ 已送达: $($obj.saved)"
        Write-Host "     体积: $([math]::Round($obj.bytes / 1KB, 1)) KB"
        Write-Host ""
        Write-Host "接下来 Mac 上会自动导入（如果 watch-inbox.sh 在跑），"
        Write-Host "否则手动: ./scripts/import-bundle.sh ~/wcu-inbox/<文件名>"
    } else {
        Write-Error "服务端拒绝: $($obj.error)"
        exit 3
    }
}

# ------------------------------------------------------------------ Pull
if ($Pull) {
    $bundle = Join-Path $env:TEMP "wcu-mac-$ts.bundle"
    Write-Host "== 从 Mac 下载 =="
    try {
        Invoke-WebRequest -Uri "$Server/bundle?token=$Token" -OutFile $bundle `
            -UseBasicParsing -TimeoutSec 120
    } catch {
        Write-Error "下载失败: $($_.Exception.Message)"
        exit 2
    }
    $size = [math]::Round((Get-Item $bundle).Length / 1KB, 1)
    Write-Host "   已下载 ($size KB)"

    Write-Host ""
    Write-Host "== 校验 =="
    git -C $repoFull bundle verify $bundle | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Remove-Item $bundle -Force -ErrorAction SilentlyContinue
        Write-Error "bundle 校验失败，可能文件损坏或缺少前置历史"
        exit 4
    }
    Write-Host "   ✓ 通过"

    Write-Host ""
    Write-Host "== 合并 =="
    git -C $repoFull fetch $bundle "refs/heads/$SyncBranch`:refs/remotes/macsync/$SyncBranch"
    if ($LASTEXITCODE -ne 0) { Write-Error "fetch 失败"; exit 5 }

    $before = git -C $repoFull rev-parse HEAD
    git -C $repoFull merge --ff-only macsync/$SyncBranch
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "⚠ 无法快进：本地有未提交改动，或两边历史分叉。"
        Write-Host "  查看: git status"
        Write-Host "  分叉: git pull --rebase macsync $SyncBranch"
        Write-Host "  回退: git reset --hard $($before.Substring(0,7))"
        Remove-Item $bundle -Force -ErrorAction SilentlyContinue
        exit 6
    }

    Remove-Item $bundle -Force -ErrorAction SilentlyContinue
    Write-Host "   ✓ 已快进到 $(git -C $repoFull rev-parse --short HEAD)"
}
