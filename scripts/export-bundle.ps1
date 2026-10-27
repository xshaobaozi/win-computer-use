#!/bin/bash
# 在 Windows 上把整个仓库打成一个 bundle 文件（单文件，含完整 git 历史）。
#
#   .\scripts\export-bundle.ps1                  # 打包当前仓库到当前目录
#   .\scripts\export-bundle.ps1 -OutDir D:\tmp   # 指定输出目录
#
# 生成的 wcu-YYYYMMDD-HHMM.bundle 可以通过任意方式传给 Mac：
# 微信 / 网盘 / U 盘 / 临时 HTTP 服务都行。

param(
    [string]$Repo = ".",
    [string]$OutDir = "."
)

$ErrorActionPreference = "Stop"

# 分支策略：只同步这一个分支。
# 故意不用 --all —— 临时/实验分支不该跟着传过去，否则会出现
# "某个分支只在这一台机器上存在"的半同步状态。
$SyncBranch = "master"

$ts = Get-Date -Format "yyyyMMdd-HHmm"
$name = "wcu-$ts.bundle"

$repoFull = (Resolve-Path $Repo).Path
if (-not (Test-Path (Join-Path $repoFull ".git"))) {
    Write-Error "不是 git 仓库: $repoFull"
    exit 1
}

$current = git -C $repoFull symbolic-ref --short HEAD
if ($current -ne $SyncBranch) {
    Write-Host "✗ 当前分支是 '$current'，同步只允许在 $SyncBranch 上操作。"
    Write-Host "  先切回: git checkout $SyncBranch"
    Write-Host "  或者把改动合到 $SyncBranch 再打包。"
    exit 10
}

$dirty = git -C $repoFull status --porcelain
if ($dirty) {
    Write-Host "⚠ 有未提交改动，这些改动不会进 bundle："
    $dirty | ForEach-Object { Write-Host "    $_" }
    Write-Host ""
}

$outFull = [System.IO.Path]::GetFullPath((Join-Path (Resolve-Path $OutDir).Path $name))

git -C $repoFull bundle create $outFull $SyncBranch
if ($LASTEXITCODE -ne 0) {
    Write-Error "打包失败"
    exit 1
}

$size = [math]::Round((Get-Item $outFull).Length / 1KB, 1)
$head = git -C $repoFull log --oneline -1

Write-Host ""
Write-Host "已生成: $outFull  ($size KB)"
Write-Host "当前提交: $head"
Write-Host ""
Write-Host "传输方式任选其一:"
Write-Host "  A) 临时 HTTP（Mac 主动来拉，Win 不用开防火墙入站以外的任何东西）:"
Write-Host "     cd $((Split-Path $outFull -Parent))"
Write-Host "     python -m http.server 8000"
Write-Host "     然后在 Mac 上: curl -O http://<本机IP>:8000/$name"
Write-Host ""
Write-Host "  B) 微信 / 网盘 / U 盘，直接把文件发过去"
Write-Host ""
Write-Host "本机 IP: $((Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.IPAddress -notlike '127.*'} | Select-Object -First 1).IPAddress)"
