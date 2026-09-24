@echo off
rem Update the 7-day high water temperature forecast (run once every morning).
rem Register in Windows Task Scheduler for automatic daily updates.
rem (ASCII only on purpose: cmd.exe misreads UTF-8 Korean text inside .bat files.)
cd /d "%~dp0.."
set PYTHONIOENCODING=utf-8
".venv\Scripts\python.exe" src\app\build_forecast.py
if errorlevel 1 (
  echo [FAILED] Forecast update failed. Check the error message above.
  exit /b 1
)
echo [DONE] Open app\index.html to see the new forecast.
