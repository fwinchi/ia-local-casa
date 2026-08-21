Set WshShell = CreateObject("WScript.Shell")
WshShell.Run """" & CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName) & "\start-mcp-correo.bat""", 0, False
