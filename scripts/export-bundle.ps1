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

$ts = Get-Date -Format "yyyyMMdd-HHmm"
$name = "wcu-$ts.bundle"

$repoFull = (Resolve-Path $Repo).Path
if (-not (Test-Path (Join-Path $repoFull ".git"))) {
    Write-Error "不是 git 仓库: $repoFull"
    exit 1
}

$outFull = [System.IO.Path]::GetFullPath((Join-Path (Resolve-Path $OutDir).Path $name))

git -C $repoFull bundle create $outFull --all
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
