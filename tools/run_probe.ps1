param(
  [string]$GameDir,
  [string]$ArgsText,
  [int]$Seconds = 8
)

$root = Split-Path -Parent $PSScriptRoot
$gameExe = Join-Path $GameDir 'core\game.exe'
$log = Join-Path $root 'probe_server.log'
$py = 'E:\anaconda3\python.exe'

Remove-Item -LiteralPath $log -ErrorAction SilentlyContinue

$server = Start-Process -FilePath $py -ArgumentList @("$root\tools\probe_server.py", "--host", "127.0.0.1", "--port", "7000", "--seconds", ($Seconds + 4), "--log", $log) -WindowStyle Hidden -PassThru
Start-Sleep -Seconds 1

$game = Start-Process -FilePath $gameExe -ArgumentList $ArgsText -WorkingDirectory $GameDir -PassThru
Start-Sleep -Seconds $Seconds

if ($game -and !$game.HasExited) { Stop-Process -Id $game.Id -Force }
if (!$server.HasExited) { Stop-Process -Id $server.Id -Force }

if (Test-Path -LiteralPath $log) {
  Get-Content -LiteralPath $log -Raw | ForEach-Object { $_.Substring(0, [Math]::Min($_.Length, 4000)) }
} else {
  'no probe log'
}
