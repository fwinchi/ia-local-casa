Set fso = CreateObject("Scripting.FileSystemObject")
target = fso.GetParentFolderName(WScript.ScriptFullName) & "\run-autocorresponsal.bat"
CreateObject("Wscript.Shell").Run """" & target & """", 0, False
