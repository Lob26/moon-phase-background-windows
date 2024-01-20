@echo off
set "ScriptDirectory=%~dp0"

::: Reload environment variables
call refreshenv

::: Run the python script
"%ScriptDirectory%pyscript\Scripts\python.exe" "%ScriptDirectory%moonback.py"
