$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$out = Join-Path $repo 'build\hosttest\app'
New-Item -ItemType Directory -Force $out | Out-Null
$gcc = (Get-Command gcc -ErrorAction SilentlyContinue).Source
if (-not $gcc) { $gcc = 'C:\mingw64\bin\gcc.exe' }
$exe = Join-Path $out 'test_app.exe'
$compilerArgs = @('-std=c11','-Wall','-Wextra','-Werror','-O1','-I',"$PSScriptRoot\app_mocks",'-I',"$repo\App\Inc",'-I',"$repo\Drivers\Tmag3001",'-I',$PSScriptRoot,"$PSScriptRoot\test_app.c","$repo\App\Src\app.c","$repo\App\Src\tmag_proto.c",'-o',$exe)
& $gcc @compilerArgs
if ($LASTEXITCODE -ne 0) { throw 'Application test compilation failed.' }
& $exe
if ($LASTEXITCODE -ne 0) { throw 'Application tests failed.' }
# Compile the real application at each supported validation rate.
foreach ($rate in @(100,200,500,1000)) {
    & $gcc '-std=c11' '-Wall' '-Wextra' '-Werror' "-DAPP_SAMPLE_RATE_HZ=$rate" '-I' "$PSScriptRoot\app_mocks" '-I' "$repo\App\Inc" '-I' "$repo\Drivers\Tmag3001" '-c' "$repo\App\Src\app.c" '-o' "$out\app_$rate.o"
    if ($LASTEXITCODE -ne 0) { throw "Application rate $rate did not compile." }
}
foreach ($rate in @(-1,0,1001,333)) {
    $diagnostics = & $gcc '-std=c11' "-DAPP_SAMPLE_RATE_HZ=$rate" '-I' "$PSScriptRoot\app_mocks" '-I' "$repo\App\Inc" '-I' "$repo\Drivers\Tmag3001" '-c' "$repo\App\Src\app.c" '-o' "$out\invalid.o" 2>&1
    if ($LASTEXITCODE -eq 0) { throw "Invalid application rate $rate was accepted." }
    if (($diagnostics -join "`n") -notmatch 'APP_SAMPLE_RATE_HZ must') { throw "Rate $rate failed for an unexpected reason: $diagnostics" }
}
Write-Output 'OK: rate compile matrix 100/200/500/1000 accepted; -1/0/1001/333 rejected.'
