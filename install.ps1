# Walkie unter Windows installieren – ohne Git, ohne Adminrechte:
#
#   irm https://raw.githubusercontent.com/julesintown/walkie/main/install.ps1 | iex
#
# Lädt den neuesten Stand als ZIP von GitHub nach %LOCALAPPDATA%\walkie\app, merkt sich Stand und
# Dateiliste (.walkie-update.json, für das Selbst-Update beim Start) und richtet ihn ein:
# Python über uv, Pakete, Stimme, Spracherkennung, Befehl `walkie`, Plugin für Claude Code
# (auch für den Code-Tab der Claude-Desktop-App). Ein zweiter Aufruf aktualisiert.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'          # Invoke-WebRequest ist mit Fortschritt sehr langsam
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$repo = if ($env:WALKIE_REPO) { $env:WALKIE_REPO } else { 'julesintown/walkie' }
$branch = if ($env:WALKIE_BRANCH) { $env:WALKIE_BRANCH } else { 'main' }
$root = if ($env:WALKIE_HOME) { $env:WALKIE_HOME } else { Join-Path $env:LOCALAPPDATA 'walkie\app' }
$headers = @{ 'User-Agent' = 'walkie-installer' }

if (Test-Path (Join-Path $root '.git')) {
  throw "$root ist ein Git-Checkout. Dort mit git pull aktualisieren."
}

Write-Host 'Walkie: neuesten Stand von GitHub holen ...'
$sha = (Invoke-WebRequest -UseBasicParsing -Headers ($headers + @{ Accept = 'application/vnd.github.sha' }) `
    "https://api.github.com/repos/$repo/commits/$branch").Content
if ($sha -is [byte[]]) { $sha = [Text.Encoding]::ASCII.GetString($sha) }
$sha = "$sha".Trim()
if ($sha -notmatch '^[0-9a-f]{40}$') { throw "Unerwartete Antwort von GitHub: $sha" }

$tmp = Join-Path $env:TEMP ('walkie-install-' + [guid]::NewGuid())
New-Item -ItemType Directory $tmp | Out-Null
try {
  $zip = Join-Path $tmp 'walkie.zip'
  Invoke-WebRequest -UseBasicParsing -Headers $headers "https://codeload.github.com/$repo/zip/$sha" -OutFile $zip
  Expand-Archive $zip -DestinationPath $tmp
  $src = Get-ChildItem $tmp -Directory | Where-Object { Test-Path (Join-Path $_.FullName 'walkie.py') } |
    Select-Object -First 1
  if (-not $src) { throw 'Das Archiv enthaelt keinen Walkie.' }

  # Walkie stoppen, falls er aus diesem Ordner laeuft (seine Dateien werden gleich ersetzt)
  $cmd = Join-Path $root 'bin\walkie.cmd'
  if (Test-Path $cmd) { & $cmd stop 2>$null | Out-Null }

  # Dateien, die es im neuen Stand nicht mehr gibt, entfernen – nur aus der alten Liste
  $files = Get-ChildItem $src.FullName -Recurse -File |
    ForEach-Object { $_.FullName.Substring($src.FullName.Length + 1).Replace('\', '/') }
  $state = Join-Path $root '.walkie-update.json'
  if (Test-Path $state) {
    $old = (Get-Content -Raw $state | ConvertFrom-Json).files
    foreach ($f in $old) {
      if ($files -notcontains $f) { Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $root $f) }
    }
  }
  New-Item -ItemType Directory -Force $root | Out-Null
  Copy-Item -Recurse -Force (Join-Path $src.FullName '*') $root
  [IO.File]::WriteAllText($state, (@{ repo = $repo; branch = $branch; sha = $sha; files = @($files | Sort-Object) } |
    ConvertTo-Json -Depth 3), (New-Object Text.UTF8Encoding $false))
} finally {
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $tmp
}

Write-Host "Walkie liegt in $root (Stand $($sha.Substring(0, 7)))."
if ($env:WALKIE_INSTALL_ONLY) { exit 0 }           # nur Dateien (Tests), nicht einrichten
Write-Host 'Einrichten ...'
$lang = if ((Get-Culture).TwoLetterISOLanguageName -eq 'de') { 'de' } else { 'en' }
& (Join-Path $root 'bin\walkie.cmd') setup --lang $lang
exit $LASTEXITCODE
