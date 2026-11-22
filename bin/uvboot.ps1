# uv für Windows laden (feste Version und SHA-256 aus uvboot.py) – von walkie.cmd aufgerufen,
# wenn kein Python da ist. Legt uv.exe nach $args[0] (…\walkie\uv\uv.exe).
$ErrorActionPreference = 'Stop'
$target = $args[0]
$src = Get-Content -Raw (Join-Path $PSScriptRoot '..\uvboot.py')
$ver = [regex]::Match($src, 'VERSION = "([^"]+)"').Groups[1].Value
$arch = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'aarch64' } else { 'x86_64' }
$name = "uv-$arch-pc-windows-msvc.zip"
$sum = [regex]::Match($src, [regex]::Escape($name) + '":\s*"([0-9a-f]{64})"').Groups[1].Value
if (-not $ver -or -not $sum) { throw 'uvboot.py: Version oder Pruefsumme fehlt' }
$tmp = Join-Path $env:TEMP ('walkie-uv-' + [guid]::NewGuid())
New-Item -ItemType Directory $tmp | Out-Null
try {
  $zip = Join-Path $tmp $name
  Invoke-WebRequest -UseBasicParsing "https://github.com/astral-sh/uv/releases/download/$ver/$name" -OutFile $zip
  if ((Get-FileHash $zip -Algorithm SHA256).Hash.ToLower() -ne $sum) { throw 'uv: Pruefsumme stimmt nicht' }
  Expand-Archive $zip -DestinationPath $tmp
  New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
  Copy-Item (Get-ChildItem $tmp -Recurse -Filter uv.exe | Select-Object -First 1).FullName $target
} finally {
  Remove-Item -Recurse -Force $tmp
}
