param([switch]$CheckOnly)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$DistIndex = Join-Path $ProjectRoot "dist\index.html"
$AppEntry = Join-Path $ProjectRoot "app.py"

function Write-Step($Message) {
    Write-Host "[InkRead] $Message" -ForegroundColor DarkRed
}

function Find-Python {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) { return $python.Source }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { return $py.Source }
    throw "未找到 Python 3。"
}

Set-Location $ProjectRoot
if (-not (Test-Path $DistIndex)) {
    Write-Step "首次启动正在构建阅读界面..."
    $npm = Get-Command npm -ErrorAction SilentlyContinue
    if (-not $npm) { throw "未找到 npm，无法生成前端文件。" }
    & $npm.Source install
    if ($LASTEXITCODE -ne 0) { throw "依赖安装失败。" }
    & $npm.Source run build
    if ($LASTEXITCODE -ne 0) { throw "前端构建失败。" }
}

$pythonExe = Find-Python
& $pythonExe -c "import fitz; from PyQt6.QtWebEngineWidgets import QWebEngineView"
if ($LASTEXITCODE -ne 0) {
    Write-Step "正在安装桌面运行依赖..."
    & $pythonExe -m pip install PyMuPDF PyQt6 PyQt6-WebEngine
    if ($LASTEXITCODE -ne 0) { throw "桌面依赖安装失败。" }
}

if ($CheckOnly) {
    Write-Step "检查通过：将以 Windows 独立窗口运行。"
    exit 0
}

$pythonDir = Split-Path -Parent $pythonExe
$pythonw = Join-Path $pythonDir "pythonw.exe"
if (-not (Test-Path $pythonw)) { $pythonw = $pythonExe }
Write-Step "正在启动砚读..."
Start-Process -FilePath $pythonw -ArgumentList ("`"{0}`"" -f $AppEntry) -WorkingDirectory $ProjectRoot
