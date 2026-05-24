$ProjectPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = "C:\Users\Adam Samad\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\python.exe"
$VenvPython = Join-Path $ProjectPath ".hector_venv\Scripts\python.exe"
$env:TEMP = Join-Path $ProjectPath "pip-temp"
$env:TMP = $env:TEMP

New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
Set-Location $ProjectPath

if (!(Test-Path $PythonExe)) {
    Write-Host "Could not find Python at $PythonExe"
    Read-Host "Press Enter to close"
    exit 1
}

if (!(Test-Path $VenvPython)) {
    Write-Host "Creating Hector private Python environment..."
    & $PythonExe -m venv (Join-Path $ProjectPath ".hector_venv")
}

if (Test-Path $VenvPython) {
    $RunPython = $VenvPython
} else {
    Write-Host "Private environment could not be created. Using managed Python fallback..."
    $RunPython = $PythonExe
}

& $RunPython -m streamlit --version | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing Hector requirements..."
    & $RunPython -m pip install --upgrade pip --break-system-packages
    & $RunPython -m pip install -r requirements.txt --break-system-packages
}

Write-Host "Starting Hector 1.5..."
& $RunPython -m streamlit run app.py
