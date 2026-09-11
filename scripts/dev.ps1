# 启动开发服务器（Windows PowerShell）
#
#   .\scripts\dev.ps1            # 自动：有 Key 用真模型，没 Key 用 mock
#   .\scripts\dev.ps1 -Mock      # 强制 mock（离线演示 / CI）
#   .\scripts\dev.ps1 -Port 8080
#
# 说明：本脚本会先同步前端 feature 注册表，再启动 FastAPI。
# 前端是免构建的 ESM，改完刷新浏览器即可，不需要打包。

param(
    [switch]$Mock,
    [int]$Port = 8000,
    [string]$HostAddr = "127.0.0.1"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "== 同步前端 feature 注册表 ==" -ForegroundColor Cyan
python scripts/gen_registry.py

if ($Mock) {
    $env:LLM_PROVIDER = "mock"
    Write-Host "== LLM_PROVIDER = mock（确定性假模型，无需 API Key）==" -ForegroundColor Yellow
} else {
    Remove-Item Env:\LLM_PROVIDER -ErrorAction SilentlyContinue
    Write-Host "== LLM_PROVIDER = auto（有 Key 走 DeepSeek，否则自动降级 mock）==" -ForegroundColor Yellow
}

$env:PYTHONIOENCODING = "utf-8"

Write-Host "== 启动后端 http://${HostAddr}:${Port} ==" -ForegroundColor Green
Set-Location "$root\backend"
python -m uvicorn app.main:app --host $HostAddr --port $Port --reload
