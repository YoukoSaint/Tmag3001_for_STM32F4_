param(
    [switch]$ReadCpuid,
    [switch]$Reset,
    [string]$ProgrammerPath = $(if ($env:STM32_PROGRAMMER_CLI) { $env:STM32_PROGRAMMER_CLI } else { 'C:\ST\STM32CubeCLT_1.21.0\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe' })
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$probeExitCode = 0
Push-Location -LiteralPath $repoRoot
try {
    if (-not (Test-Path -LiteralPath $ProgrammerPath -PathType Leaf)) {
        throw "STM32 Programmer CLI not found: $ProgrammerPath. Set -ProgrammerPath or STM32_PROGRAMMER_CLI explicitly."
    }
    Write-Host 'Listing programmer interfaces (-l); no reset requested by default.'
    & $ProgrammerPath -l
    if ($LASTEXITCODE -ne 0) { throw "Programmer interface listing failed (exit $LASTEXITCODE)." }
    if ($ReadCpuid) {
        Write-Host 'Reading CPUID at 0xE000ED00 using SWD HOTPLUG; no reset.'
        & $ProgrammerPath -c port=SWD mode=HOTPLUG -r32 0xE000ED00 1
        if ($LASTEXITCODE -ne 0) { throw "SWD HOTPLUG CPUID read failed (exit $LASTEXITCODE)." }
    }
    if ($Reset) {
        Write-Host 'Explicit -Reset requested: resetting target using SWD HOTPLUG.'
        & $ProgrammerPath -c port=SWD mode=HOTPLUG -rst
        if ($LASTEXITCODE -ne 0) { throw "Explicit target reset failed (exit $LASTEXITCODE)." }
    }
    Write-Host 'Probe command completed successfully.'
}
catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    $probeExitCode = 1
}
finally {
    Pop-Location
}
exit $probeExitCode
