$out = @()
$d = 'dist\SMC_Journal.exe'
if (Test-Path $d) {
  $gi = Get-Item $d
  $hash = (Get-FileHash $d -Algorithm SHA256).Hash
  $out += [PSCustomObject]@{path=$gi.FullName; length=$gi.Length; mtime=$gi.LastWriteTime.ToString('o'); sha256=$hash}
} else {
  $out += [PSCustomObject]@{path='dist_missing'}
}
$p = 'C:\Program Files\SMC_Journal\SMC_Journal.exe'
if (Test-Path $p) {
  $gi = Get-Item $p
  $hash = (Get-FileHash $p -Algorithm SHA256).Hash
  $out += [PSCustomObject]@{path=$gi.FullName; length=$gi.Length; mtime=$gi.LastWriteTime.ToString('o'); sha256=$hash}
} else {
  $out += [PSCustomObject]@{path='pf_missing'}
}
$out | ConvertTo-Json -Depth 4 | Out-File -FilePath .\exe_check.json -Encoding utf8
Write-Output "WROTE"
