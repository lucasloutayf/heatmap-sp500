@echo off
title S&P 500 Heatmap — Actualizando datos
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
echo.
echo [%date% %time%] Iniciando pipeline...
echo.
python run_all.py
echo.
if %errorlevel% equ 0 (
    echo [OK] Pipeline completado. Abre sp500-heatmap.html en tu navegador.
) else (
    echo [ERROR] El pipeline terminó con errores. Revisa data/cache/run.log
)
echo.
pause
