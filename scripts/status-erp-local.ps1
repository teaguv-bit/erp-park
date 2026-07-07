$ErrorActionPreference = "Continue"

Write-Host "=== TRML ERP LOCAL - STATUS ==="

Write-Host "`n=== Porta 3002 ==="
$conns = Get-NetTCPConnection -LocalPort 3002 -State Listen -ErrorAction SilentlyContinue

if ($conns) {
    $conns
} else {
    Write-Host "Nenhum processo escutando na porta 3002."
}

Write-Host "`n=== /health ==="
try {
    Invoke-RestMethod "http://localhost:3002/health" -TimeoutSec 5 | ConvertTo-Json -Depth 10
} catch {
    Write-Host "ERP não respondeu em http://localhost:3002/health"
    Write-Host $_.Exception.Message
}

Write-Host "`n=== Últimos erros ==="
$ERR = "C:\TRML_LOCAL\ERP\logs\erp-local-err.log"
if (Test-Path $ERR) {
    Get-Content $ERR -Tail 60
} else {
    Write-Host "Log de erro ainda não existe."
}

pause
