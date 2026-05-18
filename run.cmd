@echo off
setlocal
pushd "%~dp0" >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%CD%\run.ps1" %*
set EXITCODE=%ERRORLEVEL%
popd
exit /b %EXITCODE%
