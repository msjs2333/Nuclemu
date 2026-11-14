@echo off
rem Disposable sandbox only: this wrapper avoids long wsb command-line parsing.
if not exist C:\EvidenceOutput exit /b 2
set "RUNLOG=C:\EvidenceOutput\matrix-%RANDOM%-%RANDOM%.log"
echo %RUNLOG%>C:\EvidenceOutput\last-matrix-log.txt
C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "& C:\NuclemuPackaging\sandbox-acceptance.ps1 -ExpectedComputerName $env:COMPUTERNAME" >%RUNLOG% 2>&1
exit /b %ERRORLEVEL%
