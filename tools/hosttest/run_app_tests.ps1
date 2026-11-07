$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$out = Join-Path $repo 'build\hosttest\app'
New-Item -ItemType Directory -Force $out | Out-Null
$gcc = (Get-Command gcc -ErrorAction SilentlyContinue).Source
if (-not $gcc) { $gcc = 'C:\mingw64\bin\gcc.exe' }
$includes = @('-I',"$PSScriptRoot\app_mocks",'-I',"$repo\App\Inc",'-I',"$repo\Drivers\Tmag3001",'-I',$PSScriptRoot)
$strict = @('-std=c11','-Wall','-Wextra','-Werror')
$busExe = Join-Path $out 'test_i2c_bus_recovery.exe'
& $gcc @strict '-I' "$PSScriptRoot\bus_mocks" '-I' "$repo\App\Inc" '-I' $PSScriptRoot "$PSScriptRoot\test_i2c_bus_recovery.c" "$repo\Core\Src\i2c_bus_recovery.c" '-o' $busExe
if ($LASTEXITCODE -ne 0) { throw 'Bus recovery compilation failed.' }
& $busExe
if ($LASTEXITCODE -ne 0) { throw 'Bus recovery checks failed.' }
# The polling suite builds the production default without a mode override.
foreach ($suite in @('test_app_poll','test_app')) {
    $exe = Join-Path $out "$suite.exe"
    $modeArgs = @()
    if ($suite -eq 'test_app') { $modeArgs = @('-DAPP_USE_INT=1') }
    & $gcc @strict '-O1' @includes @modeArgs "$PSScriptRoot\$suite.c" "$repo\App\Src\app.c" "$repo\App\Src\tmag_proto.c" '-o' $exe
    if ($LASTEXITCODE -ne 0) { throw "$suite compilation failed." }
    & $exe
    if ($LASTEXITCODE -ne 0) { throw "$suite failed." }
}
# Compile the real application at each validation rate in both acquisition modes.
foreach ($mode in @('default','0','1')) {
    $modeArgs = @()
    if ($mode -ne 'default') { $modeArgs = @("-DAPP_USE_INT=$mode") }
    foreach ($rate in @(100,200,500,1000)) {
        & $gcc @strict @includes @modeArgs "-DAPP_SAMPLE_RATE_HZ=$rate" '-c' "$repo\App\Src\app.c" '-o' "$out\app_${mode}_$rate.o"
        if ($LASTEXITCODE -ne 0) { throw "Application mode $mode rate $rate did not compile." }
    }
}
foreach ($rate in @(-1,0,1001,333)) {
    $diagnostics = & $gcc '-std=c11' "-DAPP_SAMPLE_RATE_HZ=$rate" '-I' "$PSScriptRoot\app_mocks" '-I' "$repo\App\Inc" '-I' "$repo\Drivers\Tmag3001" '-c' "$repo\App\Src\app.c" '-o' "$out\invalid.o" 2>&1
    if ($LASTEXITCODE -eq 0) { throw "Invalid application rate $rate was accepted." }
    if (($diagnostics -join "`n") -notmatch 'APP_SAMPLE_RATE_HZ must') { throw "Rate $rate failed for an unexpected reason: $diagnostics" }
}
Write-Output 'OK: rate compile matrix 100/200/500/1000 accepted; -1/0/1001/333 rejected.'
foreach ($mode in @(-1,2)) {
    $diagnostics = & $gcc @strict @includes "-DAPP_USE_INT=$mode" '-c' "$repo\App\Src\app.c" '-o' "$out\invalid.o" 2>&1
    if ($LASTEXITCODE -eq 0) { throw "Invalid acquisition mode $mode was accepted." }
    if (($diagnostics -join "`n") -notmatch 'APP_USE_INT must') { throw "Mode $mode failed for an unexpected reason: $diagnostics" }
}
foreach ($settings in @(@('-DAPP_CONV_POLL_INTERVAL_MS=0'),@('-DAPP_CONV_TIMEOUT_MS=0'),@('-DAPP_CONV_POLL_INTERVAL_MS=6'))) {
    $diagnostics = & $gcc @strict @includes @settings '-c' "$repo\App\Src\app.c" '-o' "$out\invalid.o" 2>&1
    if ($LASTEXITCODE -eq 0) { throw "Invalid polling timing $settings was accepted." }
    if (($diagnostics -join "`n") -notmatch 'Conversion poll interval and timeout must') { throw "Polling timing failed for an unexpected reason: $diagnostics" }
}
Write-Output 'OK: acquisition modes default/0/1 accepted at all four rates; -1/2 rejected; invalid polling timing rejected.'
