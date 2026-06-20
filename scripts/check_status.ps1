$lnk=Join-Path $env:USERPROFILE 'Desktop\SMC_Journal.lnk'
$w=New-Object -ComObject WScript.Shell
$s=$w.CreateShortcut($lnk)
$target=$s.TargetPath
$wd=$s.WorkingDirectory
$pf='C:\Program Files\SMC_Journal'
$pf_exists=Test-Path $pf
$dest=Join-Path $env:LOCALAPPDATA 'SMC_Journal'
if(Test-Path $dest){ $files=Get-ChildItem -Path $dest -Force | Select-Object Name,Length } else { $files=@() }
$procs = Get-Process -Name SMC_Journal -ErrorAction SilentlyContinue | Select-Object Id,ProcessName,Path
@{shortcut_target=$target; shortcut_wd=$wd; pf_exists=$pf_exists; local_files=$files; processes=$procs} | ConvertTo-Json -Depth 4
