$ErrorActionPreference = "Continue"

$ERP = "C:\TRML_LOCAL\ERP"
$PID_FILE = "$ERP\logs\erp-local.pid"

Write-Host "=== TRML ERP LOCAL - PARAR ==="

$port = 3002
$conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue

if ($conns) {
    $procIds = $conns | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($procId in $procIds) {
        Write-Host "Parando processo PID $procId na porta 3002..."
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    }
} else {
    Write-Host "Nenhum processo escutando na porta 3002."
}

Remove-Item $PID_FILE -Force -ErrorAction SilentlyContinue

Start-Sleep -Seconds 2

$check = Get-NetTCPConnection -LocalPort 3002 -State Listen -ErrorAction SilentlyContinue

if ($check) {
    Write-Host "ATENÇÃO: ainda existe processo na porta 3002:"
    $check
} else {
    Write-Host "OK: ERP local parado e porta 3002 liberada."
}

pause
