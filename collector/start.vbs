Option Explicit
Dim shell, fs, root, python, args
Set shell = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
root = fs.GetParentFolderName(WScript.ScriptFullName)
python = shell.ExpandEnvironmentStrings("%USERPROFILE%") & "\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe"
If Not fs.FileExists(python) Then
  python = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python\Python313\pythonw.exe"
End If
If Not fs.FileExists(python) Then
  MsgBox "Python runtime not found. See README.md."
  WScript.Quit 1
End If
args = " --open"
If WScript.Arguments.Count > 0 Then args = ""
shell.CurrentDirectory = root
CreateObject("Shell.Application").ShellExecute python, "-B " & Chr(34) & root & "\app.py" & Chr(34) & args, root, "runas", 0
