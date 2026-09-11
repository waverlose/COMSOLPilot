param(
    [int]$Port = 2036
)

# Read-only reporter for the COMSOL Server that the MCP client talks to.
# Says three things the user actually needs: is it running, which port is it
# really on, and can we reach it.

$ErrorActionPreference = "Continue"

function Test-PortListening {
    param([string]$HostName, [int]$PortNumber)
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $iar = $client.BeginConnect($HostName, $PortNumber, $null, $null)
        if (-not $iar.AsyncWaitHandle.WaitOne(500)) {
            return $false
        }
        $client.EndConnect($iar)
        return $true
    }
    catch {
        return $false
    }
    finally {
        $client.Close()
    }
}

$servers = @(Get-CimInstance Win32_Process -Filter "Name='comsolmphserver.exe'" -ErrorAction SilentlyContinue)

if ($servers.Count -eq 0) {
    Write-Host "COMSOL Server : NOT RUNNING"
    Write-Host "Start it with : start_comsol_server.bat"
    exit 1
}

Write-Host "COMSOL Server : RUNNING ($($servers.Count) process(es))"

foreach ($server in $servers) {
    $declared = 0
    if ($server.CommandLine -and $server.CommandLine -match "-port\s+(\d+)") {
        $declared = [int]$Matches[1]
    }

    $listening = @()
    try {
        $listening = @(Get-NetTCPConnection -State Listen -OwningProcess $server.ProcessId -ErrorAction Stop |
            Select-Object -ExpandProperty LocalPort -Unique |
            Sort-Object)
    }
    catch {
        $listening = @()
    }

    Write-Host ""
    Write-Host "  PID            : $($server.ProcessId)"
    if ($declared -gt 0) {
        Write-Host "  Requested port : $declared"
    }
    else {
        Write-Host "  Requested port : (not given on the command line)"
    }

    if ($listening.Count -gt 0) {
        Write-Host "  Listening on   : $($listening -join ', ')"
        foreach ($localPort in $listening) {
            $reachable = Test-PortListening -HostName "localhost" -PortNumber $localPort
            $label = if ($reachable) { "yes" } else { "no" }
            Write-Host "  Reachable      : $label (localhost:$localPort)"
        }
    }
    else {
        Write-Host "  Listening on   : (nothing yet - still starting?)"
    }
}

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$statePath = Join-Path $root "workspace\runtime.json"
if (Test-Path -LiteralPath $statePath) {
    try {
        $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        Write-Host ""
        Write-Host "  Last launcher run:"
        Write-Host "    mode=$($state.mode)  port=$($state.port)  pid=$($state.pid)"
        Write-Host "    started=$($state.started_at)"
    }
    catch {
        Write-Host ""
        Write-Host "  Last launcher run: (workspace\runtime.json is unreadable)"
    }
}

Write-Host ""
Write-Host "Tip: Connect COMSOL Desktop with"
Write-Host "     File > COMSOL Multiphysics Server > Connect to Server, host localhost."

exit 0
