param(
    [int]$Port = 2036,
    [switch]$All
)

$ErrorActionPreference = "Stop"

$processes = Get-CimInstance Win32_Process |
    Where-Object {
        $_.Name -ieq "comsolmphserver.exe" -or
        ($_.CommandLine -and $_.CommandLine -match "comsolmphserver")
    }

if (-not $All) {
    $escapedPort = [regex]::Escape("$Port")
    $processes = $processes | Where-Object {
        $_.CommandLine -and $_.CommandLine -match "(^|\s)-port\s+$escapedPort(\s|$)"
    }
}

if (-not $processes) {
    if ($All) {
        Write-Host "No COMSOL Server process found."
    }
    else {
        Write-Host "No COMSOL Server process found for port $Port."
    }
    exit 0
}

foreach ($process in $processes) {
    Write-Host "Stopping COMSOL Server PID $($process.ProcessId): $($process.CommandLine)"
    Stop-Process -Id $process.ProcessId -Force
}

Write-Host "COMSOL Server stopped."
