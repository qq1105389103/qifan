param(
  [string]$GameDir,
  [string]$ArgsText,
  [int]$Seconds = 20,
  [switch]$SendA002,
  [switch]$UdpProbe,
  [switch]$TcpProbe,
  [switch]$AutoReply,
  [switch]$A002New
)

$root = Split-Path -Parent $PSScriptRoot
$gameExe = Join-Path $GameDir 'core\game.exe'
$log = Join-Path $root 'pipe_probe.log'
$py = 'E:\anaconda3\python.exe'

Remove-Item -LiteralPath $log -ErrorAction SilentlyContinue
$udpLog = Join-Path $root 'probe_server.log'
$tcpLog = Join-Path $root 'tcp_probe.log'
Remove-Item -LiteralPath $udpLog -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $tcpLog -ErrorAction SilentlyContinue

if ($UdpProbe) {
  $udp = Start-Process -FilePath $py -ArgumentList @("$root\tools\probe_server.py", "--host", "127.0.0.1", "--port", "7000", "--seconds", ($Seconds + 4), "--log", $udpLog) -WindowStyle Hidden -PassThru
}
if ($TcpProbe) {
  $tcpArgs = @("$root\tools\tcp_probe.py", "--host", "127.0.0.1", "--port", "7000", "--seconds", ($Seconds + 4), "--log", $tcpLog)
  if ($AutoReply) { $tcpArgs += "--auto-reply" }
  $tcp = Start-Process -FilePath $py -ArgumentList $tcpArgs -WindowStyle Hidden -PassThru
}

$pipeArgs = @("$root\tools\pipe_probe.py", "--name", "lanprobe", "--seconds", ($Seconds + 4), "--log", $log)
if ($SendA002) { $pipeArgs += "--send-a002" }
if ($A002New) { $pipeArgs += "--a002-new" }
$pipe = Start-Process -FilePath $py -ArgumentList $pipeArgs -WindowStyle Hidden -PassThru
Start-Sleep -Seconds 1

$game = Start-Process -FilePath $gameExe -ArgumentList $ArgsText -WorkingDirectory $GameDir -PassThru
Start-Sleep -Seconds $Seconds

if ($game -and !$game.HasExited) { Stop-Process -Id $game.Id -Force }
if ($pipe -and !$pipe.HasExited) { Stop-Process -Id $pipe.Id -Force }
if ($udp -and !$udp.HasExited) { Stop-Process -Id $udp.Id -Force }
if ($tcp -and !$tcp.HasExited) { Stop-Process -Id $tcp.Id -Force }

if (Test-Path -LiteralPath $log) {
  Get-Content -LiteralPath $log -Raw | ForEach-Object { $_.Substring(0, [Math]::Min($_.Length, 8000)) }
} else {
  'no pipe log'
}
if (Test-Path -LiteralPath $udpLog) {
  '--- udp'
  Get-Content -LiteralPath $udpLog -Raw | ForEach-Object { $_.Substring(0, [Math]::Min($_.Length, 8000)) }
}
if (Test-Path -LiteralPath $tcpLog) {
  '--- tcp'
  Get-Content -LiteralPath $tcpLog -Raw | ForEach-Object { $_.Substring(0, [Math]::Min($_.Length, 8000)) }
}
