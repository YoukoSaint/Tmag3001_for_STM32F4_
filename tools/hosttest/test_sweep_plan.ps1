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
# No actual command can run: missing initial capture must fail before directory/source mutation.
$noInitial = Run-Child @('-OutputRoot', $testOutput)
Check ($noInitial.code -ne 0 -and $noInitial.text.Contains('requires -InitialCapture')) 'Actual mode did not require initial evidence.'
Check (-not (Test-Path -LiteralPath $testOutput)) 'Rejected actual run created output.'
Check ([Convert]::ToBase64String([IO.File]::ReadAllBytes($configPath)) -ceq $before) 'Configuration bytes changed.'
Check ((Get-Location).Path -eq $beforeLocation) 'Working location changed.'

# Load only the validation function, not the command runner or script body.
$validator = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Assert-Capture' }, $true)
. ([scriptblock]::Create($validator.Extent.Text))
$fixture = [pscustomobject]@{ failure = $null; data_frames = 5; status_frames = 1
    last_status = [pscustomobject]@{ kind = 'status'; sample_rate_hz = 100; sensitivity = 885; range_code = 0; flags = 12 } }
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
Write-Host "PASS: $script:checks sweep safety/plan checks; no hardware or build executed."
