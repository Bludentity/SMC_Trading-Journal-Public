$dest=Join-Path $env:LOCALAPPDATA 'SMC_Journal'
$exe=Join-Path $dest 'SMC_Journal.exe'
if(-not (Test-Path $exe)){ Write-Output 'MISSING_LOCAL_EXE'; exit 2 }
$lnk=Join-Path $env:USERPROFILE 'Desktop\SMC_Journal.lnk'
$w=New-Object -ComObject WScript.Shell
$s=$w.CreateShortcut($lnk)
$s.TargetPath=$exe
$s.WorkingDirectory=$dest
$s.Save()
Start-Process -FilePath $exe -WindowStyle Hidden
Start-Sleep -Seconds 2
$procs=Get-Process -Name SMC_Journal -ErrorAction SilentlyContinue | Select-Object Id,ProcessName,Path
$elog=Join-Path $dest 'errors.log'
$exists=Test-Path $elog
$elogContent = if($exists){ Get-Content $elog -Tail 200 } else { 'NOLOG' }
@{shortcut_target=$s.TargetPath; shortcut_wd=$s.WorkingDirectory; processes=$procs; errors_exists=$exists; errors=$elogContent} | ConvertTo-Json -Depth 4
