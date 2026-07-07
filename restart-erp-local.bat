@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\TRML_LOCAL\ERP\scripts\stop-erp-local.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\TRML_LOCAL\ERP\scripts\start-erp-local.ps1"
