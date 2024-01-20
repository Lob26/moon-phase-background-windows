@echo off
set "ScriptDirectory=%~dp0"

::: Reload environment variables
call refreshenv
echo "Refreshed variables"

::: Run the python script
"%ScriptDirectory%pyscript\Scripts\python.exe" "%ScriptDirectory%moonback.py"
echo "Done"

pause
