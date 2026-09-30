# Builds the Windows app: dist\FSOC-PAT Setup <version>.exe and dist\win-unpacked\FSOC-PAT.exe
# Usage (from anywhere):  powershell -ExecutionPolicy Bypass -File F:\FSOC\packaging\build_exe.ps1
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

Write-Host '[1/2] Freezing Python backend (PyInstaller)...'
& "$root\venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean `
    --distpath "$root\build\pyi-dist" --workpath "$root\build\pyi-work" "$PSScriptRoot\fsoc-server.spec"
if ($LASTEXITCODE) { throw 'PyInstaller failed' }

Write-Host '[2/2] Packaging Electron app (electron-builder)...'
Push-Location "$root\frontend"
try {
    if (-not (Test-Path node_modules\electron-builder)) { npm install }
    npx electron-builder build --win --x64
    if ($LASTEXITCODE) { throw 'electron-builder failed' }
} finally { Pop-Location }

Write-Host "Done. Installer and unpacked app are in $root\dist"
