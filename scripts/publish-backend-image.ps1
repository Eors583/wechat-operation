param(
  [string]$Repository = 'ghcr.io/eors583/wechat-ai-backend'
)

$ErrorActionPreference = 'Stop'

function Invoke-Checked([string]$Command, [string[]]$Arguments) {
  & $Command @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "$Command failed with exit code $LASTEXITCODE"
  }
}

if ($Repository -notmatch '^ghcr\.io/[a-z0-9._-]+/[a-z0-9._/-]+$') {
  throw "Invalid GHCR repository: $Repository"
}

$root = Split-Path -Parent $PSScriptRoot
$dirty = & git -C $root status --porcelain
if ($LASTEXITCODE -ne 0) { throw 'Unable to read Git status' }
if ($dirty) { throw 'Commit all changes before publishing a production image' }

$shortSha = (& git -C $root rev-parse --short HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or -not $shortSha) { throw 'Unable to read Git revision' }

$tag = "git-$shortSha"
$image = "${Repository}:$tag"
$backend = Join-Path $root 'services/platform-backend'

Invoke-Checked uv @('--directory', $backend, 'run', 'ruff', 'check', '.')
Invoke-Checked docker @(
  'build', '--platform', 'linux/amd64', '--target', 'runtime',
  '--tag', $image, $backend
)
Invoke-Checked docker @('push', $image)

Write-Output "Published $image"
