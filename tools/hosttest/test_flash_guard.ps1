$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $repoRoot 'tools/flash.ps1'), [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw "flash.ps1 parse errors: $parseErrors" }
$guard = $ast.Find({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Assert-FirmwareFresh' }, $true)
if (-not $guard) { throw 'Missing dependency-aware firmware freshness guard.' }
# Load only the guard: never execute the flash entry point or programmer.
Invoke-Expression $guard.Extent.Text
$ninja = (Get-Command ninja -ErrorAction Stop).Source
$fixture = Join-Path $repoRoot ('build/flash-guard-' + [guid]::NewGuid().ToString('N'))
$build = Join-Path $fixture 'project/build'
$sdk = Join-Path $fixture 'sdk'
New-Item -ItemType Directory -Path $build, $sdk -Force | Out-Null
$utf8 = [System.Text.UTF8Encoding]::new($false)
function Write-FixtureFile([string]$Path, [string]$Text) {
    [System.IO.File]::WriteAllText($Path, $Text, $utf8)
}
$source = Join-Path $sdk 'driver.c'
$header = Join-Path $sdk 'driver.h'
Write-FixtureFile $source '#include "driver.h"'
Write-FixtureFile $header '#define SDK_VERSION 1'
$emit = Join-Path $fixture 'emit.ps1'
Write-FixtureFile $emit @'
param([string]$Output)
[System.IO.File]::WriteAllText((Join-Path (Get-Location) $Output), 'fixture artifact')
if ($Output -eq 'driver.obj') {
    [System.IO.File]::WriteAllText((Join-Path (Get-Location) 'driver.obj.d'), 'driver.obj: ../../sdk/driver.c ../../sdk/driver.h')
}
'@
$pwsh = (Get-Process -Id $PID).Path.Replace('$', '$$')
$emitForNinja = $emit.Replace('\', '/').Replace('$', '$$')
Write-FixtureFile (Join-Path $build 'build.ninja') @"
rule compile
  command = "$pwsh" -NoProfile -File "$emitForNinja" driver.obj
  depfile = driver.obj.d
  deps = gcc
rule link
  command = "$pwsh" -NoProfile -File "$emitForNinja" TMA3001_.elf
build driver.obj: compile ../../sdk/driver.c
build TMA3001_.elf: link driver.obj

"@
Write-FixtureFile (Join-Path $build 'CMakeCache.txt') "CMAKE_MAKE_PROGRAM:FILEPATH=$ninja`n"
# Only this fake graph executes commands; the commands write dummy files, with no compiler.
& $ninja -C $build TMA3001_.elf
if ($LASTEXITCODE -ne 0) { throw 'Fixture setup failed.' }
function Assert-Rejected([string]$Name) {
    $rejected = $false
    try { Assert-FirmwareFresh -BuildDirectory $build } catch { $rejected = $true }
    if (-not $rejected) { throw "FAIL: $Name was accepted." }
    Write-Host "PASS: $Name rejected"
}
Assert-FirmwareFresh -BuildDirectory $build
Write-Host 'PASS: up-to-date target accepted'
foreach ($inputFile in @($source, $header)) {
    $originalTime = [System.IO.File]::GetLastWriteTimeUtc($inputFile)
    try {
        [System.IO.File]::SetLastWriteTimeUtc($inputFile, [datetime]::UtcNow.AddMinutes(1))
        Assert-Rejected "changed selected SDK input $([System.IO.Path]::GetFileName($inputFile))"
    } finally { [System.IO.File]::SetLastWriteTimeUtc($inputFile, $originalTime) }
}
Write-FixtureFile (Join-Path $fixture 'unrelated-host.txt') 'unrelated change'
Assert-FirmwareFresh -BuildDirectory $build
Write-Host 'PASS: unrelated host file accepted'
foreach ($name in @('build.ninja', 'CMakeCache.txt', '.ninja_log', '.ninja_deps')) {
    $path = Join-Path $build $name
    Move-Item -LiteralPath $path -Destination "$path.held"
    try { Assert-Rejected "missing $name" } finally { Move-Item -LiteralPath "$path.held" -Destination $path }
}
$graphPath = Join-Path $build 'build.ninja'
$graph = [System.IO.File]::ReadAllText($graphPath)
try {
    Write-FixtureFile $graphPath 'invalid ninja graph'
    Assert-Rejected 'Ninja dry-run error'
} finally { Write-FixtureFile $graphPath $graph }
Assert-FirmwareFresh -BuildDirectory $build
Write-Host "PASS: all flash guard tests; fixture retained at $fixture"
