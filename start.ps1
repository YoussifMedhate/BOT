[CmdletBinding()]
param(
    [ValidateSet("all", "admin", "main", "dev")]
    [string]$Target = "all",
    [switch]$Check
)

$projectRoot = Split-Path -Parent $PSCommandPath
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    Write-Error "Virtual environment not found. Create it first with: py -3.11 -m venv .venv"
    exit 1
}

Set-Location -LiteralPath $projectRoot
$arguments = @("run.py")
if ($Check) {
    $arguments += "--check"
} else {
    $arguments += $Target
}

& $python @arguments
exit $LASTEXITCODE
