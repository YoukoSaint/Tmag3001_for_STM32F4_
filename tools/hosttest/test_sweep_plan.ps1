# Safe tests only: parser, DryRun, preflight refusal and in-memory status fixtures.
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$sweepPath = Join-Path $repoRoot 'tools/sweep.ps1'
$configPath = Join-Path $repoRoot 'App/Inc/app_config.h'
$shellPath = (Get-Process -Id $PID).Path
$before = [Convert]::ToBase64String([IO.File]::ReadAllBytes($configPath))
$beforeLocation = (Get-Location).Path
$testOutput = Join-Path $repoRoot ('build/sample-rate-sweep/test-' + [guid]::NewGuid().ToString('N'))
$tokens = $null; $parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($sweepPath, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
$script:checks = 0
function Check([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
    $script:checks++
}
function Run-Child([string[]]$Arguments) {
    $text = (& $shellPath -NoProfile -NonInteractive -File $sweepPath @Arguments 2>&1 | Out-String)
    return @{ text = $text; code = $LASTEXITCODE }
}
$dry = Run-Child @('-DryRun', '-OutputRoot', $testOutput)
Check ($dry.code -eq 0) "DryRun failed: $($dry.text)"
Check ($dry.text.Contains('Rates: 100, 200, 500, 1000 Hz')) 'Wrong bounded rate plan.'
Check ($dry.text.Contains('COM9 at 115200 baud; I2C 100000 Hz; 20 seconds/rate')) 'Wrong baseline plan.'
Check (([regex]::Matches($dry.text, '--require-data --json-out')).Count -eq 4) 'Expected exactly four capture commands.'
Check ($dry.text.Contains('restore original config bytes, rebuild and reflash')) 'Missing restoration plan.'
Check (-not (Test-Path -LiteralPath $testOutput)) 'DryRun created an output directory.'
$defaultDry = Run-Child @('-DryRun')
Check ($defaultDry.code -eq 0) "Default DryRun failed: $($defaultDry.text)"
$defaultOutput = [regex]::Match($defaultDry.text, 'Rates: .* Output: ([^\r\n]+)').Groups[1].Value
Check ($defaultOutput.Length -gt 0 -and -not (Test-Path -LiteralPath $defaultOutput)) 'Default DryRun created output.'
foreach ($invalid in @('relative-output', $repoRoot, (Join-Path $repoRoot 'build/../outside'), (Join-Path $repoRoot 'build'))) {
    $rejected = Run-Child @('-DryRun', '-OutputRoot', $invalid)
    Check ($rejected.code -ne 0) "Unsafe output path accepted: $invalid"
}
# Actual mode is never invoked by these tests. Verify its evidence gate precedes mutation.
$source = $ast.Extent.Text
Check ($source.IndexOf('Assert-Capture $initial 100') -lt $source.IndexOf('[IO.Directory]::CreateDirectory($OutputRoot)')) 'Initial evidence gate must precede output creation.'
Check ($source.IndexOf('Assert-Capture $initial 100') -lt $source.IndexOf('$changed = $true')) 'Initial evidence gate must precede source mutation.'
Check ($source.IndexOf('Read-SweepConfig $originalBytes') -lt $source.IndexOf('[IO.Directory]::CreateDirectory($OutputRoot)')) 'Configuration preflight must precede output creation.'
Check ($source.IndexOf('$changed = $true') -lt $source.IndexOf('[IO.File]::WriteAllText($configPath')) 'Partial writes must trigger restoration.'
$mainTry = $ast.Find({ param($node) $node -is [Management.Automation.Language.TryStatementAst] -and $null -ne $node.Finally -and $node.Finally.Extent.Text.Contains('Pop-Location') }, $true)
$restoration = $mainTry.Finally.Extent.Text
Check ($restoration.Contains('[IO.File]::WriteAllBytes($configPath, $originalBytes)')) 'Finally must restore the original bytes.'
Check ($restoration.IndexOf('Restored source bytes do not match original.') -lt $restoration.IndexOf('$summary.restoration.source_restored = $true')) 'Byte equality must precede successful restoration.'
$restoreGate = $mainTry.Finally.Find({ param($node) $node -is [Management.Automation.Language.IfStatementAst] -and $node.Clauses[0].Item1.Extent.Text -eq '$summary.restoration.source_restored' }, $true)
Check ($null -ne $restoreGate -and $restoreGate.Extent.Text.Contains("Invoke-Logged 'restore-build'")) 'Restored source must gate rebuild.'
$flashGate = $restoreGate.Find({ param($node) $node -is [Management.Automation.Language.IfStatementAst] -and $node.Clauses[0].Item1.Extent.Text -eq '$summary.restoration.rebuild_ok' }, $true)
Check ($null -ne $flashGate -and $flashGate.Extent.Text.Contains("Invoke-Logged 'restore-flash'")) 'Successful restored build must gate flash.'
Check ([Convert]::ToBase64String([IO.File]::ReadAllBytes($configPath)) -ceq $before) 'Configuration bytes changed.'
Check ((Get-Location).Path -eq $beforeLocation) 'Working location changed.'

# Load only the pure production preflight helper. Never rewrite a header.
$configValidator = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Read-SweepConfig' }, $true)
. ([scriptblock]::Create($configValidator.Extent.Text))
function Test-ConfigBytes([byte[]]$Bytes) {
    Read-SweepConfig $Bytes | Out-Null
}
$baseline = "#define APP_SAMPLE_RATE_HZ 100U`n#define APP_I2C_CLOCK_HZ 100000U`n#define APP_UART_BAUD 115200U`n#define APP_RANGE_CODE 0U`n"
$encoding = [Text.UTF8Encoding]::new($false, $true)
Test-ConfigBytes ($encoding.GetBytes($baseline))
$script:checks++
$configFailures = [Collections.Generic.List[string]]::new()
$cases = [ordered]@{}
foreach ($macro in @('APP_SAMPLE_RATE_HZ', 'APP_I2C_CLOCK_HZ', 'APP_UART_BAUD')) {
    $cases["$macro spaced duplicate"] = $encoding.GetBytes($baseline + " # define $macro 1000U`n")
    $cases["$macro tabbed duplicate"] = $encoding.GetBytes($baseline + "`t#`tdefine`t$macro`t2000U`n")
    $cases["$macro canonical duplicate"] = $encoding.GetBytes($baseline + "#define $macro 3000U`n")
    $cases["$macro mixed whitespace duplicate"] = $encoding.GetBytes($baseline + " `t# define`t$macro 4000U`n")
}
$cases['UTF-8 BOM'] = [byte[]](@(239, 187, 191) + $encoding.GetBytes("// comment`n" + $baseline))
$cases['invalid UTF-8'] = [byte[]](@(255) + $encoding.GetBytes($baseline))
foreach ($case in $cases.GetEnumerator()) {
    $refused = $false
    try { Test-ConfigBytes $case.Value } catch { $refused = $true }
    if (-not $refused) { $configFailures.Add($case.Key) }
    $script:checks++
}
if ($configFailures.Count) { throw "Preflight accepted $($configFailures.Count) unsafe fixtures: $($configFailures -join ', ')" }

# Load only the validation function, not the command runner or script body.
$validator = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Assert-Capture' }, $true)
. ([scriptblock]::Create($validator.Extent.Text))
$fixture = [pscustomobject]@{ failure = $null; data_frames = 5; status_frames = 1
    error_frames = 0; error_none_frames = 0; records = @()
    last_status = [pscustomobject]@{ kind = 'status'; sample_rate_hz = 100; sensitivity = 885; range_code = 0; flags = 12; device_status = 0; conv_status = 0; err_count = 0 } }
Assert-Capture $fixture 100
$script:checks++
foreach ($field in @('sample_rate_hz', 'sensitivity', 'range_code', 'flags')) {
    $old = $fixture.last_status.$field
    $fixture.last_status.$field = if ($field -eq 'range_code') { 1 } else { 0 }
    $refused = $false
    try { Assert-Capture $fixture 100 } catch { $refused = $true }
    Check $refused "Invalid status field accepted: $field"
    $fixture.last_status.$field = $old
}
$fixture.data_frames = 0
$refused = $false
try { Assert-Capture $fixture 100 } catch { $refused = $true }
Check $refused 'Status-only fixture accepted.'
$fixture.data_frames = 5
foreach ($flags in @(13, 14, 0, 4, 8)) {
    $fixture.last_status.flags = $flags
    $refused = $false
    try { Assert-Capture $fixture 100 } catch { $refused = $true }
    Check $refused "Faulted/not-ready capture accepted: flags=$flags"
}
$fixture.last_status.flags = 12
$fixture.failure = 'I2C_NACK'
$refused = $false
try { Assert-Capture $fixture 100 } catch { $refused = $true }
Check $refused 'Failed initial capture accepted.'
$fixture.failure = $null

# Current diagnostics and every ERROR in the captured evidence window matter,
# even if earlier DATA exists and READY/CFG flags remain set.
$faultFailures = [Collections.Generic.List[string]]::new()
function Expect-CaptureRefused($Capture, [string]$Name, [switch]$AllowTxOverflow) {
    $refused = $false
    try { Assert-Capture $Capture 100 -AllowTxOverflow:$AllowTxOverflow } catch { $refused = $true }
    if (-not $refused) { $faultFailures.Add($Name) }
    $script:checks++
}
foreach ($rawFault in @(
    @{ field = 'device_status'; value = 0x14 },
    @{ field = 'device_status'; value = 0x02 },
    @{ field = 'conv_status'; value = 0x02 })) {
    $fixture.last_status.flags = 0x4C
    $fixture.last_status.($rawFault.field) = $rawFault.value
    Expect-CaptureRefused $fixture "Raw diagnostic $($rawFault.field)=$($rawFault.value)"
    Expect-CaptureRefused $fixture "Per-rate raw diagnostic $($rawFault.field)" -AllowTxOverflow
    $fixture.last_status.($rawFault.field) = 0
}
foreach ($code in @(1, 2, 3, 4, 5, 6, 7, 8, 10, 255)) {
    $fixture.error_frames = 1
    $fixture.records = @([pscustomobject]@{ kind = 'data' }, [pscustomobject]@{ kind = 'error'; err_code = $code })
    Expect-CaptureRefused $fixture "Prior DATA then ERROR $code"
    Expect-CaptureRefused $fixture "Per-rate ERROR $code" -AllowTxOverflow
}
$fixture.records = @()
Expect-CaptureRefused $fixture 'Reported ERROR with missing details'
$fixture.error_frames = 0
$fixture.records = @([pscustomobject]@{ kind = 'error'; err_code = 9 })
Expect-CaptureRefused $fixture 'ERROR details/count mismatch' -AllowTxOverflow
$fixture.error_frames = 1
Expect-CaptureRefused $fixture 'Initial ERROR TX_OVERFLOW'
$fixture.records = @([pscustomobject]@{ kind = 'error' })
Expect-CaptureRefused $fixture 'ERROR missing code' -AllowTxOverflow
$fixture.records = @()
$fixture.error_frames = $null
Expect-CaptureRefused $fixture 'Missing ERROR count'
$fixture.error_frames = 0
$fixture.error_none_frames = 1
Expect-CaptureRefused $fixture 'Reported ERR_NONE with missing details'
$fixture.error_none_frames = 0
$fixture.last_status.device_status = $null
Expect-CaptureRefused $fixture 'Missing current DeviceStatus'
$fixture.last_status.device_status = 0
$fixture.last_status.conv_status = $null
Expect-CaptureRefused $fixture 'Missing current ConvStatus'
$fixture.last_status.conv_status = 0
if ($faultFailures.Count) { throw "Capture gate accepted $($faultFailures.Count) unsafe fixtures: $($faultFailures -join ', ')" }

$fixture.last_status.device_status = 0x10 # INT_RB alone is healthy.
$fixture.last_status.conv_status = 0x01 # Threshold crossing alone is healthy.
$fixture.last_status.err_count = 157 # Cumulative/modulo history is not a current fault.
Assert-Capture $fixture 100
$script:checks++
$fixture.records = @([pscustomobject]@{ kind = 'error'; err_code = 0 })
$fixture.error_none_frames = 1
Assert-Capture $fixture 100
$script:checks++
$fixture.records += [pscustomobject]@{ kind = 'error'; err_code = 9 }
$fixture.error_frames = 1
$fixture | Add-Member -NotePropertyName lost_frames -NotePropertyValue 3
$fixture | Add-Member -NotePropertyName discarded_bytes -NotePropertyValue 5
$fixtureBefore = $fixture | ConvertTo-Json -Depth 10 -Compress
Assert-Capture $fixture 100 -AllowTxOverflow
Check (($fixture | ConvertTo-Json -Depth 10 -Compress) -ceq $fixtureBefore) 'Per-rate validation changed overflow/loss evidence.'
$initialGate = $ast.Find({ param($node) $node -is [Management.Automation.Language.CommandAst] -and $node.Extent.Text -eq 'Assert-Capture $initial 100' }, $true)
Check ($null -ne $initialGate) 'Initial capture must use strict validation.'
Check ($source.Contains('Assert-Capture $capture $rate -AllowTxOverflow')) 'Only per-rate validation should opt into overflow measurement.'
Check ($source.Contains('error_frames = $capture.error_frames') -and $source.Contains('raw_error_codes = @($capture.records')) 'Summary must retain overflow count and codes.'
Check (-not $source.Contains('zero_loss = $true')) 'Validation must not claim zero loss.'
$hardwareCapturePath = Join-Path $repoRoot 'build/hardware/t7-postflag.json'
if (Test-Path -LiteralPath $hardwareCapturePath -PathType Leaf) {
    $hardwareCapture = Get-Content -LiteralPath $hardwareCapturePath -Raw | ConvertFrom-Json
    Expect-CaptureRefused $hardwareCapture 'Actual postflag capture'
    if ($faultFailures.Count) { throw ($faultFailures -join ', ') }
}
Check ([Convert]::ToBase64String([IO.File]::ReadAllBytes($configPath)) -ceq $before) 'Safe fixtures changed configuration bytes.'
Check (-not (Test-Path -LiteralPath $testOutput)) 'Safe fixtures created sweep output.'
Write-Host "PASS: $script:checks sweep safety/plan checks; no hardware or build executed."
