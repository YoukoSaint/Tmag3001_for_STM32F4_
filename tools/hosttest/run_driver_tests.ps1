$ErrorActionPreference = 'Stop'
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$outputDir = Join-Path $repoRoot 'build\hosttest\driver'
$testExe = Join-Path $outputDir 'test_driver.exe'
$gccCommand = Get-Command gcc -CommandType Application -ErrorAction SilentlyContinue
if ($gccCommand) { $gccPath = $gccCommand.Source }
elseif (Test-Path -LiteralPath 'C:\mingw64\bin\gcc.exe' -PathType Leaf) { $gccPath = 'C:\mingw64\bin\gcc.exe' }
else { throw 'MinGW gcc was not found.' }
New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
$compilerArgs = @('-std=c11', '-Wall', '-Wextra', '-Werror', '-O1',
    '-I', (Join-Path $PSScriptRoot 'mocks'),
    '-I', (Join-Path $repoRoot 'Drivers\Tmag3001'),
    (Join-Path $PSScriptRoot 'test_driver.c'),
    (Join-Path $repoRoot 'Drivers\Tmag3001\tmag3001_driver.c'), '-lm', '-o', $testExe)
& $gccPath @compilerArgs
if ($LASTEXITCODE -ne 0) { throw "Driver test compilation failed (exit code $LASTEXITCODE)." }
& $testExe
if ($LASTEXITCODE -ne 0) { throw "Driver tests failed (exit code $LASTEXITCODE)." }
