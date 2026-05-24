$ProjectPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = "C:\Users\Adam Samad\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\python.exe"
$VenvPython = Join-Path $ProjectPath ".hector_venv\Scripts\python.exe"
$env:TEMP = Join-Path $ProjectPath "pip-temp"
$env:TMP = $env:TEMP
$env:TMPDIR = $env:TEMP

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
    & $VenvPython -m pip --version | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Repairing Hector private Python environment..."
        & $VenvPython -m ensurepip --upgrade | Out-Null
    }
}

if (Test-Path $VenvPython) {
    & $VenvPython -m pip --version | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Recreating Hector private Python environment..."
        Remove-Item -LiteralPath (Join-Path $ProjectPath ".hector_venv") -Recurse -Force
        & $PythonExe -m venv (Join-Path $ProjectPath ".hector_venv")
        & $VenvPython -m ensurepip --upgrade | Out-Null
    }
}

if (Test-Path $VenvPython) {
    $RunPython = $VenvPython
} else {
    Write-Host "Private environment could not be created. Using managed Python fallback..."
    $RunPython = $PythonExe
}

& $RunPython -m pip --version | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Hector could not create pip in the private Python environment."
    Write-Host "Close this window, delete the .hector_venv folder, then run this launcher again."
    Read-Host "Press Enter to close"
    exit 1
}

& $RunPython -m streamlit --version | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing Hector requirements..."
    & $RunPython -m pip install --upgrade pip --break-system-packages
    & $RunPython -m pip install -r requirements.txt --break-system-packages
}

Write-Host "Starting Hector 2.3..."
& $RunPython -m streamlit run app.py
