Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("Wscript.Shell")
scriptsDir = fso.GetParentFolderName(WScript.ScriptFullName) & "\"
pyexe = sh.ExpandEnvironmentStrings("%USERPROFILE%") & "\AppData\Local\Python\bin\python.exe"
sh.Run """" & pyexe & """ """ & scriptsDir & "vigilante.py""", 0, True
sh.Run """" & pyexe & """ """ & scriptsDir & "indexar_fotos.py""", 0, True
sh.Run """" & pyexe & """ """ & scriptsDir & "indexar_videos.py""", 0, False
