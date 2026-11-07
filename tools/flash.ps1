param(
    [ValidateSet('Debug', 'Release')]
    [string]$Preset = 'Release',
    [string]$ProgrammerPath = $(if ($env:STM32_PROGRAMMER_CLI) { $env:STM32_PROGRAMMER_CLI } else { 'C:\ST\STM32CubeCLT_1.21.0\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe' })
)
$ErrorActionPreference = 'Stop'
function Assert-FirmwareFresh {
    param([Parameter(Mandatory)][string]$BuildDirectory)

    # Use the configured Ninja graph and recorded compiler header dependencies,
    # including only the selected SDK inputs. Missing metadata fails closed.
    foreach ($name in @('build.ninja', 'CMakeCache.txt', '.ninja_log', '.ninja_deps')) {
        if (-not (Test-Path -LiteralPath (Join-Path $BuildDirectory $name) -PathType Leaf)) {
            throw "Firmware freshness metadata is missing: $name. Run tools/build.ps1 first."
        }
    }
    $makeProgram = @(Get-Content -LiteralPath (Join-Path $BuildDirectory 'CMakeCache.txt') |
        Where-Object { $_ -match '^CMAKE_MAKE_PROGRAM:FILEPATH=' })
    if ($makeProgram.Count -ne 1) {
        throw 'Cannot identify configured Ninja. Run tools/build.ps1 first.'
    }
    $ninjaPath = $makeProgram[0].Substring('CMAKE_MAKE_PROGRAM:FILEPATH='.Length)
    if (-not (Test-Path -LiteralPath $ninjaPath -PathType Leaf)) {
        throw "Configured Ninja is missing: $ninjaPath"
    }
    Push-Location -LiteralPath $BuildDirectory
    try {
        # -n never executes commands, including CMake regeneration or compilers.
        # Ninja's fixed English no-work status is the only accepted output;
        # scheduled commands, warnings and native failures all reject flashing.
        $dryRun = @(& $ninjaPath -n TMA3001_.elf 2>&1)
        $ninjaExitCode = $LASTEXITCODE
        if ($ninjaExitCode -ne 0 -or $dryRun.Count -ne 1 -or
            "$($dryRun[0])" -cne 'ninja: no work to do.') {
            throw "Firmware freshness could not be confirmed (Ninja exit $ninjaExitCode): $($dryRun -join ' '). Run tools/build.ps1 first."
        }
    }
    finally { Pop-Location }
}
$repoRoot = Split-Path -Parent $PSScriptRoot
$flashExitCode = 0
Push-Location -LiteralPath $repoRoot
try {
    $elfPath = Join-Path $repoRoot "build/$Preset/TMA3001_.elf"
    if (-not (Test-Path -LiteralPath $elfPath -PathType Leaf)) {
        throw "Firmware output is missing: $elfPath. Run tools/build.ps1 -Preset $Preset first."
    }
    $elf = Get-Item -LiteralPath $elfPath
    Assert-FirmwareFresh -BuildDirectory (Join-Path $repoRoot "build/$Preset")
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
