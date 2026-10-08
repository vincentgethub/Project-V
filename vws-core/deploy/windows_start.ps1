# OPS-07: run as the same non-administrator user who completed setup.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$vwsProject = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$vwsPython = Join-Path $vwsProject '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $vwsPython -PathType Leaf)) {
    throw 'Install the hash-pinned environment and run vws setup first.'
}
Push-Location -LiteralPath $vwsProject
try {
    & $vwsPython -m vws start
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
