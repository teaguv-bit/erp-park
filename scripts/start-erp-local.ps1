$ErrorActionPreference = "Continue"

$ERP = "C:\TRML_LOCAL\ERP"
$BACKEND = "$ERP\backend"
$PY = "$BACKEND\.venv\Scripts\python.exe"
$LOG_OUT = "$ERP\logs\erp-local-out.log"
$LOG_ERR = "$ERP\logs\erp-local-err.log"
$PID_FILE = "$ERP\logs\erp-local.pid"

Write-Host "=== TRML ERP LOCAL - INICIAR ==="

if (-not (Test-Path $PY)) {
    Write-Host "ERRO: Python venv não encontrado em:"
    Write-Host $PY
    pause
    exit 1
}

$port = 3002
$conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue

if ($conns) {
    Write-Host "Porta 3002 já está em uso. Conferindo /health..."
    try {
        $health = Invoke-RestMethod "http://localhost:3002/health" -TimeoutSec 5
        Write-Host "ERP já está rodando:"
        $health | ConvertTo-Json -Depth 10
        Start-Process "http://localhost:3002"
        pause
        exit 0
    } catch {
        Write-Host "Há processo na porta 3002, mas /health falhou. Encerrando processo antigo..."
        $procIds = $conns | Select-Object -ExpandProperty OwningProcess -Unique
        foreach ($procId in $procIds) {
            Write-Host "Matando PID $procId..."
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        }
        Start-Sleep -Seconds 2
    }
}

$env:PGHOST = "127.0.0.1"
$env:PGPORT = "5432"
$env:PGDATABASE = "trml_erp"
$env:PGUSER = "postgres"

if (-not $env:PGPASSWORD) {
    $secure = Read-Host "Digite a senha do PostgreSQL" -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    $env:PGPASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
}

Write-Host "Subindo ERP local na porta 3002..."

Remove-Item $LOG_OUT -Force -ErrorAction SilentlyContinue
Remove-Item $LOG_ERR -Force -ErrorAction SilentlyContinue

$proc = Start-Process -FilePath $PY `
    -ArgumentList "-m", "uvicorn", "local_api:app", "--host", "0.0.0.0", "--port", "3002" `
    -WorkingDirectory $BACKEND `
    -PassThru `
    -RedirectStandardOutput $LOG_OUT `
    -RedirectStandardError $LOG_ERR

$proc.Id | Out-File $PID_FILE -Encoding ASCII

Start-Sleep -Seconds 4

try {
    $health = Invoke-RestMethod "http://localhost:3002/health" -TimeoutSec 10
    Write-Host "OK: ERP local iniciado com sucesso."
    $health | ConvertTo-Json -Depth 10
    Start-Process "http://localhost:3002"
} catch {
    Write-Host "ERRO: ERP não respondeu no /health."
    Write-Host "STDERR:"
    if (Test-Path $LOG_ERR) {
        Get-Content $LOG_ERR -Tail 80
    }
}

pause
