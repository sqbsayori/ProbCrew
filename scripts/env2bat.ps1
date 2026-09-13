# 把 .env 转成 cmd 能直接吃的 `SET "KEY=VALUE"` 行。
#
# 为什么单独放一个文件：在 .bat 里内联 PowerShell 需要转义 `"`，
# 而 cmd 的引号规则会让 `\"` 直接破坏 for 循环的解析（踩过）。
# 抽成一个脚本后，`启动.bat` 只负责 `for /f ... do %%L`，干净且可单测。
#
# 用法（在 启动.bat 里）：
#   for /f "usebackq delims=" %%L in (`powershell -NoProfile -ExecutionPolicy Bypass -File scripts\env2bat.ps1`) do %%L
#
# 输入：仓库根目录下的 .env（可带引号、可带 # 注释；键名统一转大写，与 pydantic-settings 一致）
# 输出：每行 `SET "KEY=VALUE"`；文件不存在则什么都不输出（调用方用默认值兜底）
# 注意：只读取，**不打印任何值到日志以外的地方**，密钥不会被写进任何文件。

param(
  [string]$Path = ".env"
)

$ErrorActionPreference = 'SilentlyContinue'

if (-not (Test-Path -LiteralPath $Path)) { return }

$dq = [string][char]34   # "
$sq = [string][char]39   # '

foreach ($raw in (Get-Content -LiteralPath $Path -Encoding UTF8)) {
  $line = $raw.Trim()
  if ($line.Length -eq 0) { continue }
  if ($line.StartsWith('#')) { continue }

  $i = $line.IndexOf('=')
  if ($i -le 0) { continue }

  $key = $line.Substring(0, $i).Trim()
  $val = $line.Substring($i + 1).Trim()
  if ($key.Length -eq 0) { continue }

  foreach ($q in @($dq, $sq)) {
    if ($val.StartsWith($q)) { $val = $val.Substring(1) }
    if ($val.EndsWith($q) -and $val.Length -gt 0) { $val = $val.Substring(0, $val.Length - 1) }
  }

  # 行内注释：pydantic-settings 不认 ` #` 后面的内容，这里对齐它的行为
  $hash = $val.IndexOf(' #')
  if ($hash -ge 0) { $val = $val.Substring(0, $hash).Trim() }

  # 输出 `SET "KEY=VALUE"`（值里若含 % 会被 cmd 二次展开，这里显式转义）
  $val = $val.Replace('%', '%%')
  'SET "{0}={1}"' -f $key.ToUpperInvariant(), $val
}
