Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\piard\Desktop\PragmaProject"
WshShell.Run "cmd.exe /c ""C:\Users\piard\Desktop\PragmaProject\scripts\start_watchdog.bat""", 0, False
