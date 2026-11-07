# One-time legacy import. Re-running copies the same bytes without nesting folders.
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$sourceRoot = 'F:\Phd\GIT_YOUKOSAINT\TMA3001_'
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$repoPrefix = $repoRoot.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
$directoryPaths = @('Core', 'Drivers\Tmag3001', 'Drivers\ST7789', 'cmake')
$toolchainPaths = @('cmake\gcc-arm-none-eabi.cmake', 'cmake\starm-clang.cmake')
$filePaths = @(
    'CMakeLists.txt',
    'CMakePresets.json',
    'startup_stm32f411xe.s',
    'STM32F411XX_FLASH.ld',
    'TMA3001_.ioc'
)

function Assert-RepoDestination([string] $RelativePath) {
    $destination = [IO.Path]::GetFullPath((Join-Path $repoRoot $RelativePath))
    if (-not $destination.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Destination is outside the repository: $destination"
    }
    # Do not follow an existing junction or symbolic link outside the repository.
    $ancestor = $destination
    while ($ancestor -and $ancestor -ne $repoRoot) {
        if (Test-Path -LiteralPath $ancestor) {
            $entry = Get-Item -LiteralPath $ancestor -Force
            if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Destination contains a reparse point: $ancestor"
            }
        }
        $ancestor = Split-Path -Parent $ancestor
    }
}

# Validate every source and destination before creating or copying anything.
foreach ($relativePath in $directoryPaths) {
    $source = Join-Path $sourceRoot $relativePath
    if (-not (Test-Path -LiteralPath $source -PathType Container)) {
        throw "Required source directory is missing: $source"
    }
    Assert-RepoDestination $relativePath
}
foreach ($relativePath in ($toolchainPaths + $filePaths)) {
    $source = Join-Path $sourceRoot $relativePath
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "Required source file is missing: $source"
    }
    Assert-RepoDestination $relativePath
}
foreach ($relativePath in $directoryPaths[0..2]) {
    foreach ($entry in (Get-ChildItem -LiteralPath (Join-Path $sourceRoot $relativePath) -Recurse -Force)) {
        $suffix = $entry.FullName.Substring($sourceRoot.Length).TrimStart('\', '/')
        Assert-RepoDestination $suffix
    }
}

foreach ($relativePath in $directoryPaths) {
    $destination = Join-Path $repoRoot $relativePath
    $null = New-Item -ItemType Directory -Path $destination -Force
    if ($relativePath -eq 'cmake') {
        foreach ($toolchainPath in $toolchainPaths) {
            Copy-Item -LiteralPath (Join-Path $sourceRoot $toolchainPath) -Destination (Join-Path $repoRoot $toolchainPath) -Force
        }
    } else {
        foreach ($entry in (Get-ChildItem -LiteralPath (Join-Path $sourceRoot $relativePath) -Force)) {
            Copy-Item -LiteralPath $entry.FullName -Destination $destination -Recurse -Force
        }
    }
    Write-Output "Copied directory: $relativePath"
}
foreach ($relativePath in $filePaths) {
    Copy-Item -LiteralPath (Join-Path $sourceRoot $relativePath) -Destination (Join-Path $repoRoot $relativePath) -Force
    Write-Output "Copied file: $relativePath"
}
Write-Output 'Done. cmake/stm32cubemx was deliberately omitted; only the two toolchain files were copied.'
