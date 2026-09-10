@echo off
rem ---------------------------------------------------------------------------
rem  Double-clickable front door for cr.py.
rem
rem  It exists for three reasons, all of them things that go wrong before any
rem  Python runs:
rem
rem   - the working directory. python-dotenv finds .env by walking up from the
rem     current directory, so a run started from somewhere else authenticates
rem     differently from one started in the repo. This cd's to the repo root
rem     first, every time.
rem   - the virtual environment. If .venv exists it is used, because a machine
rem     with anthropic installed globally and not in .venv (or the reverse)
rem     otherwise fails with an ImportError that reads like a missing file.
rem   - the window closing. Double-clicked, a .cmd closes on exit and takes the
rem     refusal message with it - which is the entire output of a failed run.
rem
rem  Arguments are passed straight through:
rem     run.cmd --doctor
rem     run.cmd --minutes 15 --synthesize
rem  With none, it runs the doctor, because that is the safe default: it looks
rem  at the machine and touches nothing.
rem ---------------------------------------------------------------------------

setlocal
set "HERE=%~dp0"
cd /d "%HERE%.."

set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

set "ARGS=%*"
if "%ARGS%"=="" set "ARGS=--doctor"

"%PY%" "%HERE%cr.py" %ARGS%
set "CODE=%ERRORLEVEL%"

echo.
if "%CODE%"=="0" (
  echo finished.
) else (
  echo exited %CODE% - the reason is in the output above, and a refusal always
  echo says whether anything was tapped.
)

rem Only pause when launched from Explorer. Run from a terminal, a pause here
rem would hang a script that called this.
echo %CMDCMDLINE% | find /i "/c" >nul && pause

exit /b %CODE%
