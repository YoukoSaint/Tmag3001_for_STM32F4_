$ErrorActionPreference = 'Stop'

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$outputDir = Join-Path $repoRoot 'build\hosttest'
$testExe = Join-Path $outputDir 'test_proto.exe'

$gccCommand = Get-Command gcc -CommandType Application -ErrorAction SilentlyContinue
if ($gccCommand) {
    $gccPath = $gccCommand.Source
} elseif (Test-Path -LiteralPath 'C:\mingw64\bin\gcc.exe' -PathType Leaf) {
    $gccPath = 'C:\mingw64\bin\gcc.exe'
} else {
    throw 'MinGW gcc was not found in PATH or C:\mingw64\bin\gcc.exe.'
}

New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
$compilerArgs = @(
    '-std=c11'
    '-Wall'
    '-Wextra'
    '-Werror'
    '-O1'
    '-I', (Join-Path $repoRoot 'App\Inc')
    '-I', $PSScriptRoot
    (Join-Path $PSScriptRoot 'test_proto.c')
    (Join-Path $repoRoot 'App\Src\tmag_proto.c')
    '-o', $testExe
)

& $gccPath @compilerArgs
if ($LASTEXITCODE -ne 0) {
    throw "Host test compilation failed (exit code $LASTEXITCODE)."
}

& $testExe
exit $LASTEXITCODE
