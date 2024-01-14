Set WshShell = CreateObject("WScript.Shell")

' Get the directory where the VBScript is located
ScriptDirectory = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)

' Build the full paths using the ScriptDirectory variable
PythonInterpreter = ScriptDirectory & "\pyscript\Scripts\python.exe"
PythonScript = ScriptDirectory & "\moonback.py"

' Run the Python script
WshShell.Run Chr(34) & PythonInterpreter & Chr(34) & " " & Chr(34) & PythonScript & Chr(34), 0

Set WshShell = Nothing

