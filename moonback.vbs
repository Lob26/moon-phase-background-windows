Set WshShell = CreateObject("WScript.Shell" ) 

' Get the value of %userprofile% and store it in a variable
UserProfile = WshShell.ExpandEnvironmentStrings("%userprofile%")

' Build the full paths using the UserProfile variable
PythonInterpreter = UserProfile & "\Documents\MoonPhaseBGPY\pyscript\Scripts\python.exe"
PythonScript = UserProfile & "\Documents\MoonPhaseBGPY\moonback.py"

' Run the Python script
WshShell.Run Chr(34) & PythonInterpreter & Chr(34) & " " & Chr(34) & PythonScript & Chr(34), 0 

Set WshShell = Nothing

