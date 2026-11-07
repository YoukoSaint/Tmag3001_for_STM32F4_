<#
Bounded sample-rate experiment. Actual execution requires a prior T7 capture.
DryRun reads paths/configuration only. No firmware or measured results are fabricated.
The UART/I2C baselines stay 115200 baud / 100 kHz; no automatic tuning occurs.
#>
[CmdletBinding()]
param(
    [ValidateSet('Release')][string]$Preset = 'Release',
    [string]$Port = 'COM9',
    [ValidateSet(115200)][int]$Baud = 115200,
    [ValidateRange(1, 300)][int]$Seconds = 20,
    [string]$Python = 'C:\ProgramData\Anaconda3\python.exe',
    [string]$OutputRoot,
    [string]$InitialCapture,
    [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
$repoRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$configPath = Join-Path $repoRoot 'App/Inc/app_config.h'
$rates = @(100, 200, 500, 1000)
$utf8 = [Text.UTF8Encoding]::new($false, $true)
$buildScript = Join-Path $PSScriptRoot 'build.ps1'
$flashScript = Join-Path $PSScriptRoot 'flash.ps1'
$captureScript = Join-Path $PSScriptRoot 'hosttest/test_capture.py'
$shellPath = (Get-Process -Id $PID).Path
$exitCode = 0
$changed = $false
$outputCreated = $false
$summary = [ordered]@{
    started_utc = [DateTime]::UtcNow.ToString('o')
    completed_utc = $null
    port = $Port; baud = $Baud; i2c_clock_hz = 100000
    seconds_per_rate = $Seconds; rates = $rates
    initial_capture = $InitialCapture
    commands = [Collections.Generic.List[object]]::new()
    results = [Collections.Generic.List[object]]::new()
    failure = $null
    restoration = [ordered]@{ source_restored = $false; rebuild_ok = $false; reflash_ok = $false; failures = @() }
    interpretation = 'Observed bounded tests only; the last successful rate is not a physical maximum. Sequence loss is modulo 256 across all frame kinds; status err_count is modulo 256.'
}

function Assert-Capture($Capture, [int]$Rate) {
    if ($Capture.failure -or $Capture.data_frames -lt 1 -or $Capture.status_frames -lt 1) {
        throw 'Capture must contain status and DATA frames with no capture failure.'
    }
    $status = $Capture.last_status
    if ($null -eq $status -or $status.kind -ne 'status' -or
        $status.sample_rate_hz -ne $Rate -or $status.sensitivity -ne 885 -or
        $status.range_code -ne 0 -or ($status.flags -band 3) -ne 0 -or
        ($status.flags -band 12) -ne 12) {
        throw "Status does not confirm rate=$Rate, sensitivity=885, range=0, SENSOR_READY and CFG_OK."
    }
}

function Read-SweepConfig([byte[]]$Bytes) {
    if ($Bytes.Length -ge 3 -and $Bytes[0] -eq 0xEF -and $Bytes[1] -eq 0xBB -and $Bytes[2] -eq 0xBF) {
        throw 'Configuration must be UTF-8 without BOM.'
    }
    $text = [Text.UTF8Encoding]::new($false, $true).GetString($Bytes)
    foreach ($macro in @('APP_SAMPLE_RATE_HZ', 'APP_I2C_CLOCK_HZ', 'APP_UART_BAUD', 'APP_RANGE_CODE')) {
        # Count all directive spellings before requiring the canonical baseline below.
        # Horizontal C whitespace includes tabs; a macro-name boundary also counts function-like definitions.
        $definitionPattern = '(?m)^[\t\x0B\x0C ]*#[\t\x0B\x0C ]*define[\t\x0B\x0C ]+' + [regex]::Escape($macro) + '\b'
        if ([regex]::Matches($text, $definitionPattern).Count -ne 1) {
            throw "Expected exactly one definition of $macro."
        }
    }
    $rateMatches = [regex]::Matches($text, '(?m)^#define APP_SAMPLE_RATE_HZ ([0-9]+)U\r?$')
    if ($rateMatches.Count -ne 1 -or $rateMatches[0].Groups[1].Value -ne '100') {
        throw 'Expected exactly one #define APP_SAMPLE_RATE_HZ 100U baseline.'
    }
    foreach ($baseline in @('APP_I2C_CLOCK_HZ 100000U', 'APP_UART_BAUD 115200U', 'APP_RANGE_CODE 0U')) {
        if ([regex]::Matches($text, '(?m)^#define ' + [regex]::Escape($baseline) + '\r?$').Count -ne 1) {
            throw "Unexpected baseline: $baseline"
        }
    }
    return @{ Text = $text; RateMatch = $rateMatches[0] }
}

function Invoke-Logged([string]$Label, [string]$Executable, [string[]]$Arguments) {
    $logPath = Join-Path $OutputRoot ($Label + '.log')
    $entry = [ordered]@{ label = $Label; executable = $Executable; arguments = $Arguments
        started_utc = [DateTime]::UtcNow.ToString('o'); exit_code = $null; log = $logPath; elf_sha256 = $null }
    $summary.commands.Add($entry)
    Write-Host "Running $Label (log: $logPath)"
    & $Executable @Arguments *>> $logPath
    $entry.exit_code = $LASTEXITCODE
    if ($entry.exit_code -ne 0) { throw "$Label failed with exit $($entry.exit_code); see $logPath" }
    if ($Label -like '*build*') {
        $elf = Join-Path $repoRoot "build/$Preset/TMA3001_.elf"
        $entry.elf_sha256 = (Get-FileHash -LiteralPath $elf -Algorithm SHA256).Hash
    }
}

Push-Location -LiteralPath $repoRoot
try {
    foreach ($required in @($configPath, $buildScript, $flashScript, $captureScript, $Python, $shellPath)) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Required file missing: $required" }
    }
    $originalBytes = [IO.File]::ReadAllBytes($configPath)
    $config = Read-SweepConfig $originalBytes
    $originalText = $config.Text
    $matches = @($config.RateMatch)
    if (-not $OutputRoot) {
        $OutputRoot = Join-Path $repoRoot ('build/sample-rate-sweep/' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
    }
    if (-not [IO.Path]::IsPathRooted($OutputRoot)) { throw 'OutputRoot must be absolute and inside repository build/.' }
    $OutputRoot = [IO.Path]::GetFullPath($OutputRoot)
    $buildRoot = [IO.Path]::GetFullPath((Join-Path $repoRoot 'build'))
    if (-not $OutputRoot.StartsWith($buildRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'OutputRoot must be a new directory inside repository build/.'
    }
    # Reject junction/symlink ancestors so lexical containment also means physical containment.
    $ancestor = $OutputRoot
    while ($ancestor -and $ancestor -ne $repoRoot) {
        if (Test-Path -LiteralPath $ancestor) {
            if ((Get-Item -LiteralPath $ancestor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Output path contains a reparse point: $ancestor"
            }
        }
        $ancestor = Split-Path -Parent $ancestor
    }
    if (Test-Path -LiteralPath $OutputRoot) { throw 'OutputRoot already exists; choose a new directory to preserve previous files.' }
    Write-Host "Plan: Release; $Port at $Baud baud; I2C 100000 Hz; $Seconds seconds/rate."
    Write-Host "Rates: $($rates -join ', ') Hz. Output: $OutputRoot"
    foreach ($rate in $rates) {
        Write-Host "[$rate Hz] change only APP_SAMPLE_RATE_HZ; build.ps1 -Preset Release; flash.ps1 -Preset Release"
        Write-Host "[$rate Hz] $Python $captureScript --port $Port --baud $Baud --seconds $Seconds --require-data --json-out $OutputRoot/rate-$rate/capture.json"
    }
    Write-Host 'Finally: restore original config bytes, rebuild and reflash Release; report restoration failures separately.'
    if ($DryRun) { return }
    if (-not $InitialCapture -or -not (Test-Path -LiteralPath $InitialCapture -PathType Leaf)) {
        throw 'Actual execution requires -InitialCapture pointing to a successful prior T7 JSON capture.'
    }
    $initial = Get-Content -LiteralPath $InitialCapture -Raw | ConvertFrom-Json
    Assert-Capture $initial 100
    if ($initial.port -ne $Port -or $initial.baud -ne $Baud) { throw 'Initial capture port/baud does not match this sweep.' }
    [IO.Directory]::CreateDirectory($OutputRoot) | Out-Null
    $outputCreated = $true
    [IO.File]::WriteAllBytes((Join-Path $OutputRoot 'original-app_config.h'), $originalBytes)
    $summary.initial_capture_sha256 = (Get-FileHash -LiteralPath $InitialCapture -Algorithm SHA256).Hash
    foreach ($rate in $rates) {
        $rateRoot = Join-Path $OutputRoot "rate-$rate"
        [IO.Directory]::CreateDirectory($rateRoot) | Out-Null
        $result = [ordered]@{ requested_rate_hz = $rate; capture = (Join-Path $rateRoot 'capture.json'); validated = $false; failure = $null; facts = $null }
        $summary.results.Add($result)
        try {
            $replacement = $originalText.Substring(0, $matches[0].Groups[1].Index) + $rate + $originalText.Substring($matches[0].Groups[1].Index + $matches[0].Groups[1].Length)
            # Mark before writing: even a partial failed write requires restoration.
            $changed = $true
            [IO.File]::WriteAllText($configPath, $replacement, $utf8)
            Invoke-Logged "rate-$rate-build" $shellPath @('-NoProfile', '-NonInteractive', '-File', $buildScript, '-Preset', $Preset)
            Invoke-Logged "rate-$rate-flash" $shellPath @('-NoProfile', '-NonInteractive', '-File', $flashScript, '-Preset', $Preset)
            $captureCommandFailure = $null
            try {
                Invoke-Logged "rate-$rate-capture" $Python @($captureScript, '--port', $Port, '--baud', "$Baud", '--seconds', "$Seconds", '--require-data', '--json-out', $result.capture)
            }
            catch { $captureCommandFailure = $_ }
            try {
                if (Test-Path -LiteralPath $result.capture -PathType Leaf) {
                    $capture = Get-Content -LiteralPath $result.capture -Raw | ConvertFrom-Json
                    $result.facts = [ordered]@{
                        data_hz = $capture.data_hz; data_frames = $capture.data_frames; elapsed_seconds = $capture.elapsed_seconds
                        lost_frames = $capture.lost_frames; discarded_bytes = $capture.discarded_bytes
                        duplicate_frames = $capture.duplicate_frames; error_frames = $capture.error_frames
                        error_none_frames = $capture.error_none_frames; last_status = $capture.last_status
                        raw_error_codes = @($capture.records | Where-Object { $_.kind -eq 'error' } | ForEach-Object { $_.err_code })
                        trigger_int = [bool]($capture.last_status.flags -band 16)
                        int_path_ok = [bool]($capture.last_status.flags -band 32)
                        capture_failure = $capture.failure
                    }
                }
            }
            catch {
                if ($null -eq $captureCommandFailure) { throw }
                $result.facts = @{ read_failure = $_.Exception.Message }
            }
            if ($null -ne $captureCommandFailure) { throw $captureCommandFailure }
            Assert-Capture $capture $rate
            $result.validated = $true
        }
        catch { $result.failure = $_.Exception.Message; throw }
    }
}
catch { $summary.failure = $_.Exception.Message; $exitCode = 1; [Console]::Error.WriteLine($summary.failure) }
finally {
    if ($changed) {
        try {
            [IO.File]::WriteAllBytes($configPath, $originalBytes)
            if ([Convert]::ToBase64String([IO.File]::ReadAllBytes($configPath)) -ne [Convert]::ToBase64String($originalBytes)) { throw 'Restored source bytes do not match original.' }
            $summary.restoration.source_restored = $true
        }
        catch { $summary.restoration.failures += $_.Exception.Message; $exitCode = 1 }
        if ($summary.restoration.source_restored) {
            try {
                Invoke-Logged 'restore-build' $shellPath @('-NoProfile', '-NonInteractive', '-File', $buildScript, '-Preset', $Preset)
                $summary.restoration.rebuild_ok = $true
            }
            catch { $summary.restoration.failures += $_.Exception.Message; $exitCode = 1 }
            # Never flash a stale ELF if the restored build failed.
            if ($summary.restoration.rebuild_ok) {
                try {
                    Invoke-Logged 'restore-flash' $shellPath @('-NoProfile', '-NonInteractive', '-File', $flashScript, '-Preset', $Preset)
                    $summary.restoration.reflash_ok = $true
                }
                catch { $summary.restoration.failures += $_.Exception.Message; $exitCode = 1 }
            }
        }
    }
    if ($outputCreated) {
        $summary.completed_utc = [DateTime]::UtcNow.ToString('o')
        try {
            $temporary = Join-Path $OutputRoot 'summary.json.tmp'
            [IO.File]::WriteAllText($temporary, ($summary | ConvertTo-Json -Depth 30), $utf8)
            [IO.File]::Move($temporary, (Join-Path $OutputRoot 'summary.json'))
            Write-Host "Facts and restoration outcome: $OutputRoot/summary.json"
        }
        catch { $exitCode = 1; [Console]::Error.WriteLine("Summary save failed: $($_.Exception.Message)") }
    }
    foreach ($failure in $summary.restoration.failures) { [Console]::Error.WriteLine("RESTORATION FAILED: $failure") }
    Pop-Location
}
exit $exitCode
