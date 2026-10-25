# One-click campus walkway demo. Run from any directory.
Set-Location (Join-Path $PSScriptRoot "..")
uv run python -m final_agent.campus_demo
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
