Set WshShell = CreateObject("WScript.Shell")

ScriptDirectory = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)

' Run the Python script
WshShell.Run Chr(34) & ScriptDirectory & "\moonback.bat" & Chr(34), 0, True

Set WshShell = Nothing

