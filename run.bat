@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
set "LOG_FILE=%~dp0run.log"

> "%LOG_FILE%" echo [%date% %time%] HSS Truss Designer launcher started
>> "%LOG_FILE%" echo Script directory initialized
>> "%LOG_FILE%" echo User: %USERNAME%

call :log Checking Python availability
call :ensure_python || goto :fail
call :log Python command selected: %PY_CMD% %PY_ARGS%
if defined PY_EXE call :log Python executable resolved to: %PY_EXE%
call :ensure_gui_python
if defined PY_GUI_CMD call :log GUI Python command selected: %PY_GUI_CMD% %PY_GUI_ARGS%
call :requirements_ready && goto :launch

call :log Required packages missing. Starting installation.
echo Installing required Python packages...
call :install_requirements || goto :fail

:launch
call :log Launching application
call :launch_app || goto :fail
call :log Launcher finished successfully
exit /b 0

:log
>> "%LOG_FILE%" echo [%date% %time%] %*
exit /b 0

:ensure_python
set "BROKEN_PYTHON_PATH="
for %%P in (py python3 python) do (
	call :try_python_command %%P && goto :python_found
)

if defined BROKEN_PYTHON_PATH (
	call :log Found Python executable but Windows would not run it: %BROKEN_PYTHON_PATH%
	echo Found Python at:
	echo   %BROKEN_PYTHON_PATH%
	echo.
	echo Windows refused to run that executable. This usually means the installed Python is incompatible with the PC architecture, blocked by security policy, or corrupted.
	echo Reinstall Python using the correct installer for that PC, then rerun this launcher.
	exit /b 1
)

call :log Python interpreter not found in PATH. Attempting winget install.
echo Python interpreter not found. Attempting install via winget...
where winget >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
	call :log winget is not available on this system.
	echo winget is not available. Install Python manually and rerun this script.
	exit /b 1
)
winget install --id Python.Python.3.11 --exact --silent --source winget >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
	call :log Python automatic installation failed.
	echo Failed to install Python automatically. Install Python from https://www.python.org/downloads/ and rerun this script.
	exit /b 1
)

:python_found
for %%P in (py python3 python) do (
	call :try_python_command %%P && exit /b 0
)
call :log Python installation completed but PATH still does not resolve a Python command.
echo Python installation succeeded but executable still not located in PATH.
echo Please restart the terminal or log out/in, then rerun this script.
exit /b 1

:try_python_command
set "PY_CMD="
set "PY_ARGS="
set "PY_EXE="

if /i "%~1"=="py" (
	where py >> "%LOG_FILE%" 2>&1
	for /f "usebackq delims=" %%E in (`where py 2^>nul`) do (
		call :validate_python_candidate "%%E" "-3" "py" && exit /b 0
	)
	call :log Candidate rejected: py
	exit /b 1
)

where %1 >> "%LOG_FILE%" 2>&1
for /f "usebackq delims=" %%E in (`where %1 2^>nul`) do (
	call :validate_python_candidate "%%E" "" "%~1" && exit /b 0
)
call :log Candidate rejected: %1
exit /b 1

:validate_python_candidate
set "PY_CHECK_FILE=%TEMP%\hss_truss_python_check_%RANDOM%%RANDOM%.txt"
"%~1" %~2 -c "import os, sys; print(os.path.realpath(sys.executable))" > "!PY_CHECK_FILE!" 2>nul
if errorlevel 1 goto :python_candidate_failed
set /p PY_EXE=<"!PY_CHECK_FILE!"
del "!PY_CHECK_FILE!" >nul 2>&1
set "PY_CMD=%~1"
set "PY_ARGS=%~2"
goto :python_candidate_found

:python_candidate_failed
del "!PY_CHECK_FILE!" >nul 2>&1
echo %~1 | find /i "WindowsApps" >nul
if errorlevel 1 (
	set "BROKEN_PYTHON_PATH=%~1"
)
call :log Candidate path rejected: %~3 to %~1
exit /b 1

:python_candidate_found
echo !PY_EXE! | find /i "WindowsApps" >nul
if not errorlevel 1 (
	call :log Candidate rejected because it is a WindowsApps alias: !PY_CMD! !PY_ARGS! to !PY_EXE!
	set "PY_CMD="
	set "PY_ARGS="
	set "PY_EXE="
	exit /b 1
)
call :log Candidate accepted: !PY_CMD! !PY_ARGS! to !PY_EXE!
exit /b 0

:ensure_gui_python
set "PY_GUI_CMD="
set "PY_GUI_ARGS="
if defined PY_EXE (
	for %%D in ("%PY_EXE%") do set "PY_DIR=%%~dpD"
	if exist "!PY_DIR!pythonw.exe" (
		set "PY_GUI_CMD=!PY_DIR!pythonw.exe"
		exit /b 0
	)
)
where pyw >> "%LOG_FILE%" 2>&1 && (
	for /f "usebackq delims=" %%E in (`pyw -c "import os, sys; print(os.path.realpath(sys.executable))" 2^>nul`) do (
		set "PY_GUI_CMD=pyw"
		set "PY_GUI_ARGS=-3"
		exit /b 0
	)
)
where pythonw >> "%LOG_FILE%" 2>&1 && (
	set "PY_GUI_CMD=pythonw"
		exit /b 0
)
call :log GUI Python command not found. Will fall back to console Python.
exit /b 0

:requirements_ready
"%PY_CMD%" %PY_ARGS% -c "import numpy, matplotlib" >> "%LOG_FILE%" 2>&1
if errorlevel 1 call :log Dependency import check failed.
exit /b %errorlevel%

:install_requirements
if not exist requirements.txt (
	call :log requirements.txt is missing.
	echo requirements.txt missing.
	exit /b 1
)
echo Installing required Python packages...
"%PY_CMD%" %PY_ARGS% -m pip install --upgrade pip --no-warn-script-location >> "%LOG_FILE%" 2>&1
"%PY_CMD%" %PY_ARGS% -m pip install --prefer-binary --no-warn-script-location -r requirements.txt >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
	call :log Python package installation failed.
	echo Failed to install Python packages.
	exit /b 1
)
call :log Python package installation completed.
exit /b 0

:launch_app
if defined PY_GUI_CMD (
	call :log Starting GUI process: %PY_GUI_CMD% %PY_GUI_ARGS% launch_app.py
	start "" /b "%PY_GUI_CMD%" %PY_GUI_ARGS% launch_app.py
	exit /b 0
)
call :log Starting console Python process: %PY_CMD% %PY_ARGS% launch_app.py
echo Running application with %PY_CMD% %PY_ARGS% ...
start "" /b "%PY_CMD%" %PY_ARGS% launch_app.py
exit /b 0

:fail
call :log Launcher failed. Opening log file.
start "" notepad.exe "%LOG_FILE%"
exit /b 1
