param(
    [ValidateSet('Debug', 'Release')]
    [string]$Preset = 'Release'
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$buildExitCode = 0
Push-Location -LiteralPath $repoRoot
try {
    & cmake --preset $Preset
    if ($LASTEXITCODE -ne 0) { throw "CMake configuration failed (exit $LASTEXITCODE)." }
    & cmake --build --preset $Preset
    if ($LASTEXITCODE -ne 0) { throw "Firmware build failed (exit $LASTEXITCODE)." }
    $elfPath = Join-Path $repoRoot "build/$Preset/TMA3001_.elf"
    if (-not (Test-Path -LiteralPath $elfPath -PathType Leaf)) { throw "Firmware output is missing: $elfPath" }
    & arm-none-eabi-size $elfPath
    if ($LASTEXITCODE -ne 0) { throw "Firmware size check failed (exit $LASTEXITCODE)." }
    Write-Host "Firmware ready: $elfPath"
}
catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    $buildExitCode = 1
}
finally {
    Pop-Location
}
exit $buildExitCode
