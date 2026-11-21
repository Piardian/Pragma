$readingDir = (Get-Item 'C:\Users\piard\Documents\Codex\2026-11-07\https-youtu-be-j-6bhln-d70\outputs\*READ*\reading').FullName
Set-Location $readingDir

python manage.py start
Start-Sleep -Seconds 4
python manage.py status
