$ErrorActionPreference = "Continue"

$ERP = "C:\TRML_LOCAL\ERP"
$BACKEND = "$ERP\backend"
$PY = "$BACKEND\.venv\Scripts\python.exe"
$LOG_OUT = "$ERP\backups\DIAG_backend_local_stdout.log"
$LOG_ERR = "$ERP\backups\DIAG_backend_local_stderr.log"
$IMPORT_TEST = "$ERP\scripts\diag_import_api.py"

Write-Host "=== DIAGNOSTICO BACKEND LOCAL V3 ==="
Write-Host "Backend: $BACKEND"
Write-Host "Python: $PY"
Write-Host "Log OUT: $LOG_OUT"
Write-Host "Log ERR: $LOG_ERR"

cd $BACKEND

Write-Host "`n=== Python version ==="
& $PY --version

Write-Host "`n=== Py compile ==="
& $PY -m py_compile api.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERRO: api.py não compilou."
    exit 1
}

Write-Host "`n=== Criando teste de import em Python ==="

@"
import sys
import traceback

backend = r"$BACKEND"
if backend not in sys.path:
    sys.path.insert(0, backend)

try:
    import api
    app = getattr(api, "app", None)
    print("IMPORT_OK=", bool(app))
    if app:
        print("ROUTES_COUNT=", len(getattr(app, "routes", [])))
        for r in getattr(app, "routes", [])[:60]:
            print("ROUTE=", getattr(r, "path", ""), getattr(r, "methods", ""))
except Exception:
    print("IMPORT_ERROR")
    traceback.print_exc()
"@ | Set-Content $IMPORT_TEST -Encoding UTF8

Write-Host "`n=== Testando import do api.py ==="
& $PY $IMPORT_TEST

Write-Host "`n=== Liberando porta 3002, se necessário ==="
$conns = Get-NetTCPConnection -LocalPort 3002 -State Listen -ErrorAction SilentlyContinue
if ($conns) {
    $procIds = $conns | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($procId in $procIds) {
        Write-Host "Matando PID $procId na porta 3002..."
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2
}

Write-Host "`n=== Limpando logs antigos ==="
Remove-Item $LOG_OUT -Force -ErrorAction SilentlyContinue
Remove-Item $LOG_ERR -Force -ErrorAction SilentlyContinue

Write-Host "`n=== Subindo uvicorn por teste na porta 3002 ==="

$env:PORT = "3002"
$env:TRML_LOCAL_MODE = "true"

$proc = Start-Process -FilePath $PY `
    -ArgumentList "-m", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", "3002" `
    -WorkingDirectory $BACKEND `
    -PassThru `
    -RedirectStandardOutput $LOG_OUT `
    -RedirectStandardError $LOG_ERR

Write-Host "PID backend teste: $($proc.Id)"
Start-Sleep -Seconds 8

Write-Host "`n=== Testando /health ==="
try {
    $health = Invoke-RestMethod "http://localhost:3002/health" -TimeoutSec 10
    $health | ConvertTo-Json -Depth 10
} catch {
    Write-Host "Falhou ao chamar /health:"
    Write-Host $_.Exception.Message
}

Write-Host "`n=== Testando porta 3002 ==="
Get-NetTCPConnection -LocalPort 3002 -State Listen -ErrorAction SilentlyContinue

Write-Host "`n=== Parando backend de teste ==="
if ($proc -and $proc.Id) {
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 1

Write-Host "`n=== Últimas linhas STDOUT ==="
if (Test-Path $LOG_OUT) {
    Get-Content $LOG_OUT -Tail 80
} else {
    Write-Host "STDOUT não encontrado."
}

Write-Host "`n=== Últimas linhas STDERR ==="
if (Test-Path $LOG_ERR) {
    Get-Content $LOG_ERR -Tail 120
} else {
    Write-Host "STDERR não encontrado."
}

Write-Host "`n=== Diagnóstico finalizado ==="
