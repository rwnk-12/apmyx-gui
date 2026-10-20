@echo off
powershell.exe -NoLogo -NoProfile -File "%~dp0scripts\wrappers\setup-qemu.ps1" %*
set "setup_result=%errorlevel%"
if not "%setup_result%"=="0" pause
if "%~1"=="" if "%setup_result%"=="0" pause
exit /b %setup_result%
