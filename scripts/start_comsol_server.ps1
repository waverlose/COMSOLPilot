param(
    [int]$Port = 2036,
    # Server authentication mode:
    #   auto  - clients must log in (a Desktop login is required first)
    #   never - no authentication; any local/API client may connect
    #   info  - ask only for missing login information
    #   force - always ask for login information
    [ValidateSet("auto", "never", "info", "force")]
    [string]$LoginMode = "auto",
    [int]$Cores = 0,
    [string]$Version = "",
    [string]$ServerExe = "",
    [string]$PythonExe = "",
    [int]$TimeoutSeconds = 90,
    # GUI mode: after the server is ready, also launch the COMSOL Desktop so the
    # user only has to pick File > COMSOL Multiphysics Server > Connect to Server.
    [switch]$OpenDesktop
)

$ErrorActionPreference = "Stop"

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

function Test-PortBindable {
    # Listening on a port and being able to *bind* it are different questions.
    # Windows happily hands out an ephemeral source port that is still inside a
    # live outbound socket, so Test-PortListening reports "free" while COMSOL's
    # bind fails and it silently falls back to the next port.
    param([int]$PortNumber)
    try {
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Any, $PortNumber)
        $listener.Start()
        $listener.Stop()
        return $true
    }
    catch {
        return $false
    }
}

function Find-FreePort {
    param([int]$StartPort, [int]$Window = 10)
    for ($candidate = $StartPort; $candidate -le $StartPort + $Window; $candidate++) {
        if ((Test-PortBindable -PortNumber $candidate) -and -not (Test-PortListening -HostName "localhost" -PortNumber $candidate)) {
            return $candidate
        }
    }
    return 0
}

function Get-ListeningPortFromLog {
    # COMSOL announces its real port on stdout, e.g.
    # "端口号 2036 忙，改用 2037" / "开始在端口 2037 上监听"
    # "... listening on port 2037"
    param([string]$LogPath)
    if (-not (Test-Path -LiteralPath $LogPath)) {
        return 0
    }
    $text = (Get-Content -LiteralPath $LogPath -Raw -ErrorAction SilentlyContinue)
    if (-not $text) {
        return 0
    }
    $matches = [regex]::Matches($text, '(?:port|端口)\s*[:\s]?\s*(\d{2,5})')
    for ($i = $matches.Count - 1; $i -ge 0; $i--) {
        $value = [int]$matches[$i].Groups[1].Value
        if ($value -gt 0) {
            return $value
        }
    }
    return 0
}

function Find-PythonExe {
    param([string]$Explicit)
    if ($Explicit -and (Test-Path -LiteralPath $Explicit)) {
        return (Resolve-Path -LiteralPath $Explicit).Path
    }
    if ($env:COMSOL_PYTHON -and (Test-Path -LiteralPath $env:COMSOL_PYTHON)) {
        return (Resolve-Path -LiteralPath $env:COMSOL_PYTHON).Path
    }
    # The project venv is the one interpreter guaranteed to have MPh installed.
    # Preferring a system/Anaconda python here used to break COMSOL version
    # discovery in complete silence.
    $venvPython = Join-Path $root ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython) {
        return (Resolve-Path -LiteralPath $venvPython).Path
    }
    $candidates = @(
        "D:\anaconda\envs\comsolpilot\python.exe",
        "$env:USERPROFILE\anaconda3\envs\comsolpilot\python.exe",
        "$env:USERPROFILE\miniconda3\envs\comsolpilot\python.exe"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }
    return ""
}

function Find-ComsolServerExe {
    param([string]$Explicit, [string]$Py, [string]$ComsolVersion)
    if ($Explicit -and (Test-Path -LiteralPath $Explicit)) {
        return (Resolve-Path -LiteralPath $Explicit).Path
    }
    if ($env:COMSOL_SERVER_EXE -and (Test-Path -LiteralPath $env:COMSOL_SERVER_EXE)) {
        return (Resolve-Path -LiteralPath $env:COMSOL_SERVER_EXE).Path
    }
    # Cache from a previous launch: runtime.json records what worked last time,
    # so a warm start skips the (slow) discovery attempts below entirely.
    # An explicitly requested version never reuses the cache: the cached path
    # belongs to whichever version ran last, and install folders such as
    # E:\COMSOL64 do not contain the dotted version string, so the cache cannot
    # be matched by name - switching versions would silently keep the old one.
    try {
        $runtimePath = Join-Path $root "workspace\runtime.json"
        if (Test-Path -LiteralPath $runtimePath) {
            $cached = (Get-Content -LiteralPath $runtimePath -Raw | ConvertFrom-Json).server_exe
            $useCache = -not $ComsolVersion
            if ($cached -and $useCache -and (Test-Path -LiteralPath $cached)) {
                return $cached
            }
        }
    }
    catch {
    }
    # Version -> executable mapping comes from MPh's own discovery, exposed by
    # list_comsol_versions.py as JSON. The previous inline one-liner discarded
    # stderr and swallowed exceptions, so a python without MPh silently fell
    # through to the pattern list below and returned whichever install matched
    # first - asking for 6.4 quietly started 6.2.
    $mapper = Join-Path $root "scripts\list_comsol_versions.py"
    if ($Py -and (Test-Path -LiteralPath $mapper)) {
        # Run the enumerator out-of-process: `& $Py script.py` cannot be used in
        # a pipeline here, and Start-Process aborts on duplicated proxy variable
        # spellings, so the environment is normalised first and the JSON is
        # collected through a temp file.
        Remove-DuplicateCaseEnvironmentVariables
        $raw = ""
        $tmpOut = Join-Path $env:TEMP ("comsol_versions_{0}.json" -f $PID)
        $tmpErr = "$tmpOut.err"
        try {
            Start-Process -FilePath $Py -ArgumentList ('"{0}"' -f $mapper) -NoNewWindow -Wait `
                -RedirectStandardOutput $tmpOut -RedirectStandardError $tmpErr
        }
        catch {
            $raw = ""
        }
        if (Test-Path -LiteralPath $tmpOut) {
            try {
                $raw = (Get-Content -LiteralPath $tmpOut -Raw)
            }
            catch {
                $raw = ""
            }
            Remove-Item -LiteralPath $tmpOut -ErrorAction SilentlyContinue
        }
        Remove-Item -LiteralPath $tmpErr -ErrorAction SilentlyContinue
        # The helper prints one JSON line; keep the last non-empty line so a
        # stray warning on stdout cannot break parsing.
        if ($raw) {
            $lines = @($raw -split "`r?`n" | Where-Object { $_.Trim() })
            if ($lines.Count -gt 0) {
                $raw = $lines[-1]
            }
        }
        $data = $null
        if ($raw) {
            try {
                $data = $raw | ConvertFrom-Json
            }
            catch {
                $data = $null
            }
        }
        if ($data -and $data.success -and $data.versions) {
            if ($ComsolVersion) {
                $hit = $data.versions | Where-Object { $_.name -eq $ComsolVersion } | Select-Object -First 1
                if ($hit -and $hit.server -and (Test-Path -LiteralPath $hit.server)) {
                    return (Resolve-Path -LiteralPath $hit.server).Path
                }
                $found = ($data.versions | ForEach-Object { $_.name }) -join ", "
                throw "COMSOL $ComsolVersion was requested but it is not installed (MPh found: $found)."
            }
            # No version requested: newest discovered installation.
            $latest = $data.versions | Select-Object -Last 1
            if ($latest -and $latest.server -and (Test-Path -LiteralPath $latest.server)) {
                return (Resolve-Path -LiteralPath $latest.server).Path
            }
        }
        if ($ComsolVersion) {
            throw "Cannot resolve COMSOL ${ComsolVersion}: MPh discovery failed (run menu [6] Diagnose)."
        }
    }
    if ($ComsolVersion) {
        throw "Cannot resolve COMSOL ${ComsolVersion}: no python with MPh found. Pass -PythonExe or set COMSOL_PYTHON."
    }

    $patterns = @(
        "C:\Program Files\COMSOL\*\Multiphysics\bin\win64\comsolmphserver.exe",
        "C:\Program Files\COMSOL*\Multiphysics\bin\win64\comsolmphserver.exe",
        "C:\Program Files\COMSOL*\*\Multiphysics\bin\win64\comsolmphserver.exe",
        "D:\COMSOL*\Multiphysics\bin\win64\comsolmphserver.exe",
        "D:\COMSOL*\*\Multiphysics\bin\win64\comsolmphserver.exe",
        "E:\COMSOL*\Multiphysics\bin\win64\comsolmphserver.exe",
        "E:\COMSOL*\*\Multiphysics\bin\win64\comsolmphserver.exe",
        "E:\Comsol*\Multiphysics\bin\win64\comsolmphserver.exe",
        "E:\Comsol*\*\Multiphysics\bin\win64\comsolmphserver.exe"
    )
    foreach ($pattern in $patterns) {
        $matches = Get-ChildItem -Path $pattern -ErrorAction SilentlyContinue | Sort-Object FullName -Descending
        if ($matches) {
            return $matches[0].FullName
        }
    }
    return ""
}

function Remove-DuplicateCaseEnvironmentVariables {
    # Windows environment variables are case-insensitive, but they can be exposed
    # twice under different spellings (HTTPS_PROXY + https_proxy - common behind a
    # corporate or local proxy). Start-Process rebuilds the child environment from
    # a case-SENSITIVE dictionary and then aborts with
    #   "An item with the same key has already been added. Key: 'https_proxy'"
    # which makes the whole launch fail before COMSOL is even started.
    # Dropping the duplicate spelling is lossless: lookups are case-insensitive,
    # so the surviving spelling still resolves to the same value.
    $seen = @{}
    $removed = 0
    foreach ($entry in [Environment]::GetEnvironmentVariables().GetEnumerator()) {
        $name = [string]$entry.Key
        $canonical = $name.ToUpperInvariant()
        if ($seen.ContainsKey($canonical)) {
            Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
            $removed++
        }
        else {
            $seen[$canonical] = $true
        }
    }
    if ($removed -gt 0) {
        Write-Host "Normalised $removed duplicate-case environment variable(s) before starting COMSOL."
    }
}

function Find-ComsolDesktopExe {
    # The Desktop sits next to the server in every COMSOL install we have seen,
    # so prefer that; fall back to the usual install roots.
    param([string]$ServerExe)
    if ($env:COMSOL_DESKTOP_EXE -and (Test-Path -LiteralPath $env:COMSOL_DESKTOP_EXE)) {
        return (Resolve-Path -LiteralPath $env:COMSOL_DESKTOP_EXE).Path
    }
    try {
        $runtimePath = Join-Path $root "workspace\runtime.json"
        if (Test-Path -LiteralPath $runtimePath) {
            $cached = (Get-Content -LiteralPath $runtimePath -Raw | ConvertFrom-Json).desktop_exe
            # Only reuse the cached Desktop when it sits in the same install as
            # the server we are about to start - otherwise selecting 6.2 would
            # still open the 6.4 Desktop.
            $sameInstall = $true
            if ($ServerExe -and $cached) {
                $sameInstall = ((Split-Path -Parent $cached) -eq (Split-Path -Parent $ServerExe))
            }
            if ($cached -and $sameInstall -and (Test-Path -LiteralPath $cached)) {
                return $cached
            }
        }
    }
    catch {
    }
    if ($ServerExe) {
        $candidate = Join-Path (Split-Path -Parent $ServerExe) "comsol.exe"
        if (Test-Path -LiteralPath $candidate) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    $patterns = @(
        "C:\Program Files\COMSOL\*\Multiphysics\bin\win64\comsol.exe",
        "C:\Program Files\COMSOL*\Multiphysics\bin\win64\comsol.exe",
        "C:\Program Files\COMSOL*\*\Multiphysics\bin\win64\comsol.exe",
        "D:\COMSOL*\Multiphysics\bin\win64\comsol.exe",
        "D:\COMSOL*\*\Multiphysics\bin\win64\comsol.exe",
        "E:\COMSOL*\Multiphysics\bin\win64\comsol.exe",
        "E:\COMSOL*\*\Multiphysics\bin\win64\comsol.exe",
        "E:\Comsol*\Multiphysics\bin\win64\comsol.exe",
        "E:\Comsol*\*\Multiphysics\bin\win64\comsol.exe"
    )
    foreach ($pattern in $patterns) {
        $found = Get-ChildItem -Path $pattern -ErrorAction SilentlyContinue | Sort-Object FullName -Descending
        if ($found) {
            return $found[0].FullName
        }
    }
    return ""
}

function Write-RuntimeState {
    # A tiny machine-readable record of what we just started, so the launcher can
    # report status and keep the MCP client's COMSOL_PORT in sync without
    # re-deriving anything.
    param(
        [int]$RealPort,
        [int]$ProcessId,
        [string]$ServerExe,
        [string]$DesktopExe,
        [string]$Mode,
        [string]$ComsolVersion
    )
    try {
        $stateDir = Join-Path $root "workspace"
        New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
        $state = [ordered]@{
            port        = $RealPort
            host        = "localhost"
            pid         = $ProcessId
            mode        = $Mode
            server_exe  = $ServerExe
            desktop_exe = $DesktopExe
            comsol_version = $ComsolVersion
            started_at  = (Get-Date).ToString("s")
        }
        $state | ConvertTo-Json | ForEach-Object {
            # Write BOM-less UTF-8: Set-Content -Encoding UTF8 in Windows
            # PowerShell 5.1 always emits a BOM, which breaks naive JSON readers.
            [System.IO.File]::WriteAllText((Join-Path $stateDir "runtime.json"), $_,
                [System.Text.UTF8Encoding]::new($false))
        }
    }
    catch {
        Write-Warning "Could not write workspace\runtime.json: $($_.Exception.Message)"
    }
}

function Start-ComsolDesktop {
    param([string]$DesktopExe, [int]$RealPort)
    if (-not $DesktopExe) {
        Write-Warning "Could not locate comsol.exe. Open COMSOL Desktop yourself, then use File > COMSOL Multiphysics Server > Connect to Server."
        return
    }
    try {
        Remove-DuplicateCaseEnvironmentVariables
        Start-Process -FilePath $DesktopExe | Out-Null
        Write-Host ""
        Write-Host "COMSOL Desktop launched. Connect it to the server with:"
        Write-Host "    File > COMSOL Multiphysics Server > Connect to Server"
        Write-Host "      Server : localhost"
        Write-Host "      Port   : $RealPort"
        Write-Host ""
    }
    catch {
        Write-Warning "Failed to launch COMSOL Desktop: $($_.Exception.Message)"
    }
}

function Complete-Startup {
    param([int]$RealPort, [int]$ProcessId, [string]$ServerExe, [string]$Mode)
    $desktopExe = Find-ComsolDesktopExe -ServerExe $ServerExe
    Write-RuntimeState -RealPort $RealPort -ProcessId $ProcessId -ServerExe $ServerExe -DesktopExe $desktopExe -Mode $Mode -ComsolVersion $Version
    if ($OpenDesktop) {
        Start-ComsolDesktop -DesktopExe $desktopExe -RealPort $RealPort
    }
}

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$logDir = Join-Path $root "workspace\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$mode = if ($OpenDesktop) { "gui" } else { "headless" }

if (Test-PortListening -HostName "localhost" -PortNumber $Port) {
    Write-Host "COMSOL Server is already listening on localhost:$Port"
    $owner = 0
    try {
        $connection = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction Stop | Select-Object -First 1
        if ($connection) { $owner = [int]$connection.OwningProcess }
    }
    catch {
        $owner = 0
    }
    Complete-Startup -RealPort $Port -ProcessId $owner -ServerExe "" -Mode $mode
    exit 0
}

# "Not listening" is not the same as "bindable": Windows can hand the port out as
# an ephemeral source port for a live outbound socket. COMSOL's bind then fails and
# it silently relocates, while this script keeps waiting on the requested port and
# finally reports a timeout for a server that did in fact start.
if (-not (Test-PortBindable -PortNumber $Port)) {
    $fallbackPort = Find-FreePort -StartPort ($Port + 1)
    if ($fallbackPort -eq 0) {
        throw "Port $Port cannot be bound and no free port was found within the next 10. Free the port and retry."
    }
    Write-Warning "Port $Port is not bindable (held by another process, often an ephemeral socket). Using $fallbackPort instead."
    Write-Warning "Point the MCP client at it with COMSOL_PORT=$fallbackPort, or it will look on the wrong port."
    $Port = $fallbackPort
}

# Same for the authentication mode: the launcher's choice (settings.json) is
# used when the switch is missing, so the .bat and the menu behave alike.
if (-not $PSBoundParameters.ContainsKey("LoginMode")) {
    try {
        $settingsPath = Join-Path $root "workspace\settings.json"
        if (Test-Path -LiteralPath $settingsPath) {
            $configured = [string]((Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json).login_mode)
            if ($configured -in @("auto", "never", "info", "force")) {
                $LoginMode = $configured
            }
        }
    }
    catch {
    }
}

$resolvedPython = Find-PythonExe -Explicit $PythonExe

# No -Version on the command line: honour the version picked in the launcher
# (workspace/settings.json), so double-clicking the .bat behaves exactly like
# starting from the menu and cannot silently launch the other installation.
if (-not $Version) {
    try {
        $settingsPath = Join-Path $root "workspace\settings.json"
        if (Test-Path -LiteralPath $settingsPath) {
            $Version = [string]((Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json).comsol_version)
        }
    }
    catch {
        $Version = ""
    }
    if ($Version) {
        Write-Host "COMSOL version from settings.json: $Version"
    }
}

$resolvedServer = Find-ComsolServerExe -Explicit $ServerExe -Py $resolvedPython -ComsolVersion $Version
if (-not $resolvedServer) {
    throw "Cannot find comsolmphserver.exe. Pass -ServerExe or set COMSOL_SERVER_EXE."
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$stdoutLog = Join-Path $logDir "comsol_server_$Port`_$timestamp.out.log"
$stderrLog = Join-Path $logDir "comsol_server_$Port`_$timestamp.err.log"

$arguments = @("-login", $LoginMode, "-graphics", "-autosave", "off", "-port", "$Port", "-multi", "on")
if ($LoginMode -eq "never") {
    Write-Warning "LoginMode=never: this server accepts unauthenticated clients on port $Port."
}
if ($Cores -gt 0) {
    $arguments += @("-np", "$Cores")
}

Remove-DuplicateCaseEnvironmentVariables

$process = Start-Process `
    -FilePath $resolvedServer `
    -ArgumentList $arguments `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -WindowStyle Hidden `
    -PassThru

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$sw = [System.Diagnostics.Stopwatch]::StartNew()
Write-Host "Waiting for the server to come up (usually 30-60 s; the JVM boot is the slow part) ..."
while ((Get-Date) -lt $deadline) {
    if ($process.HasExited) {
        $tail = ""
        if (Test-Path -LiteralPath $stdoutLog) {
            $tail = (Get-Content -LiteralPath $stdoutLog -Tail 20 -ErrorAction SilentlyContinue) -join "`n"
        }
        throw "COMSOL Server exited before port $Port became ready.`n$tail"
    }
    if (Test-PortListening -HostName "localhost" -PortNumber $Port) {
        Write-Host "COMSOL Server started on localhost:$Port"
        Write-Host "Process ID: $($process.Id)"
        Write-Host "Log: $stdoutLog"
        Complete-Startup -RealPort $Port -ProcessId $process.Id -ServerExe $resolvedServer -Mode $mode
        exit 0
    }
    # Safety net: if COMSOL relocates anyway, believe its own log over our guess.
    $announced = Get-ListeningPortFromLog -LogPath $stdoutLog
    if ($announced -gt 0 -and $announced -ne $Port -and (Test-PortListening -HostName "localhost" -PortNumber $announced)) {
        Write-Warning "COMSOL bound port $announced instead of the requested $Port."
        Write-Host "COMSOL Server started on localhost:$announced"
        Write-Host "Process ID: $($process.Id)"
        Write-Host "Log: $stdoutLog"
        Write-Warning "The launcher will point the MCP client at COMSOL_PORT=$announced automatically."
        Complete-Startup -RealPort $announced -ProcessId $process.Id -ServerExe $resolvedServer -Mode $mode
        exit 0
    }
    if ([math]::Floor($sw.Elapsed.TotalSeconds) % 5 -eq 0 -and [math]::Floor($sw.Elapsed.TotalSeconds) -gt 0) {
        Write-Host ("  ... still waiting ({0:n0} s)" -f $sw.Elapsed.TotalSeconds)
    }
    Start-Sleep -Milliseconds 500
}

$announced = Get-ListeningPortFromLog -LogPath $stdoutLog
$hint = if ($announced -gt 0) { " COMSOL reported port $announced in its log." } else { "" }
throw "Timed out waiting for COMSOL Server on localhost:$Port.$hint Logs: $stdoutLog"
