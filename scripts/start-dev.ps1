Param(
  [switch]$SkipSync
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backendDir = Join-Path $repoRoot "backend"
$frontendDir = Join-Path $repoRoot "frontend"

if (-not (Test-Path $backendDir)) {
  throw "Backend directory not found: $backendDir"
}
if (-not (Test-Path $frontendDir)) {
  throw "Frontend directory not found: $frontendDir"
}

$backendCommand = @(
  "Set-Location '$backendDir'"
  "Write-Host 'Starting backend on http://127.0.0.1:8000 ...' -ForegroundColor Green"
  ($(if ($SkipSync) { "Write-Host 'Skip uv sync by request.' -ForegroundColor Yellow" } else { "uv sync" }))
  "uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
) -join "; "

$frontendCommand = @(
  "Set-Location '$frontendDir'"
  "Write-Host 'Starting frontend on http://127.0.0.1:5173 ...' -ForegroundColor Cyan"
  "if (-not (Test-Path 'node_modules')) { npm install }"
  "npm run dev"
) -join "; "

Start-Process powershell -ArgumentList @(
  "-NoExit",
  "-ExecutionPolicy", "Bypass",
  "-Command", $backendCommand
)

Start-Process powershell -ArgumentList @(
  "-NoExit",
  "-ExecutionPolicy", "Bypass",
  "-Command", $frontendCommand
)

Write-Host "Dev services are launching in two new windows." -ForegroundColor Green
Write-Host "Backend:  http://127.0.0.1:8000" -ForegroundColor Green
Write-Host "Frontend: http://127.0.0.1:5173" -ForegroundColor Green
