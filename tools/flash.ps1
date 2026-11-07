param(
    [ValidateSet('Debug', 'Release')]
    [string]$Preset = 'Release',
    [string]$ProgrammerPath = $(if ($env:STM32_PROGRAMMER_CLI) { $env:STM32_PROGRAMMER_CLI } else { 'C:\ST\STM32CubeCLT_1.21.0\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe' })
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$flashExitCode = 0
Push-Location -LiteralPath $repoRoot
try {
    $elfPath = Join-Path $repoRoot "build/$Preset/TMA3001_.elf"
    if (-not (Test-Path -LiteralPath $elfPath -PathType Leaf)) {
        throw "Firmware output is missing: $elfPath. Run tools/build.ps1 -Preset $Preset first."
    }
    $elf = Get-Item -LiteralPath $elfPath
    # A conservative source/configuration freshness check; never rebuild or
    # silently select another artifact inside the flash operation.
    $inputs = @('App/Inc', 'App/Src', 'Core/Inc', 'Core/Src', 'Drivers/Tmag3001') | ForEach-Object {
        Get-ChildItem -LiteralPath (Join-Path $repoRoot $_) -Recurse -File |
            Where-Object { $_.Extension -in @('.c', '.h', '.s') }
    }
    $inputs += @('CMakeLists.txt', 'CMakePresets.json', 'cmake/firmware_sources.cmake', 'cmake/gcc-arm-none-eabi.cmake', 'STM32F411XX_FLASH.ld', 'startup_stm32f411xe.s') | ForEach-Object {
        Get-Item -LiteralPath (Join-Path $repoRoot $_)
    }
    $newer = $inputs | Where-Object { $_.LastWriteTimeUtc -gt $elf.LastWriteTimeUtc } | Select-Object -First 1
    if ($newer) {
        throw "Firmware may be stale: $($newer.FullName) is newer than $elfPath. Rebuild preset $Preset first."
    }
    if (-not (Test-Path -LiteralPath $ProgrammerPath -PathType Leaf)) {
        throw "STM32 Programmer CLI not found: $ProgrammerPath. Set -ProgrammerPath or STM32_PROGRAMMER_CLI explicitly."
    }
    Write-Host "Flash preset=$Preset ELF=$elfPath modifiedUTC=$($elf.LastWriteTimeUtc.ToString('o')) SHA256=$((Get-FileHash -LiteralPath $elfPath -Algorithm SHA256).Hash)"
    Write-Host 'Writing over SWD, verifying programmed memory (-v), then resetting target (-rst).'
    & $ProgrammerPath -c port=SWD -w $elfPath -v -rst
    if ($LASTEXITCODE -ne 0) { throw "Firmware write/verify/reset failed (exit $LASTEXITCODE)." }
    Write-Host 'Programmer CLI completed write, verification and reset successfully.'
}
catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    $flashExitCode = 1
}
finally {
    Pop-Location
}
exit $flashExitCode
