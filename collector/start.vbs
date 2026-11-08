Option Explicit
Dim shell, fs, root, python, args
Set shell = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
root = fs.GetParentFolderName(WScript.ScriptFullName)
python = shell.ExpandEnvironmentStrings("%USERPROFILE%") & "\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe"
If Not fs.FileExists(python) Then
  python = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python\Python313\pythonw.exe"
End If
If fs.FileExists(root & "\.venv\Scripts\pythonw.exe") Then
  python = root & "\.venv\Scripts\pythonw.exe"
End If
If fs.FileExists(root & "\.runtime\pythonw.exe") Then
  python = root & "\.runtime\pythonw.exe"
End If
If Not fs.FileExists(python) Then
  MsgBox "Python runtime not found. See README.md."
  WScript.Quit 1
End If
' The pre-authorized scheduled task is the only server launch path.
Dim service, task
On Error Resume Next
Set service = CreateObject("Schedule.Service")
service.Connect
Set task = service.GetFolder("\").GetTask("KiwoomTop100Archive_2005")
If Err.Number <> 0 Then
  MsgBox "Collector scheduled task missing. Run install_schedule.ps1 as administrator once."
  WScript.Quit 1
End If
If task.Definition.Principal.RunLevel <> 1 Then
  MsgBox "Collector task must use highest privileges. Reinstall the task as administrator once."
  WScript.Quit 1
End If
Err.Clear
If task.State <> 4 Then task.Run Null
If Err.Number <> 0 Then
  MsgBox "Collector scheduled launch failed. Check Task Scheduler."
  WScript.Quit 1
End If
On Error GoTo 0
If WScript.Arguments.Count = 0 Then
  shell.CurrentDirectory = root
  shell.Run Chr(34) & python & Chr(34) & " -B " & Chr(34) & root & "\window.py" & Chr(34), 0, False
End If
