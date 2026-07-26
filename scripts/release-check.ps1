# Esports Isolator PRO release readiness gate.
param(
  [switch]$SkipPackage
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$UiPackage = Get-Content -LiteralPath "ui/package.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$ReleaseVersion = $UiPackage.version
$InstallerArtifact = "Esports Isolator PRO Setup $ReleaseVersion.exe"

function Invoke-Step {
  param(
    [Parameter(Mandatory = $true)][string]$Name,
    [Parameter(Mandatory = $true)][scriptblock]$Command
  )

  Write-Host "`n== $Name ==" -ForegroundColor Cyan
  # Reset before and capture immediately after: a step whose last command is
  # a cmdlet (not a native exe) leaves $LASTEXITCODE untouched, which would
  # otherwise re-report a stale exit code from a previous step.
  $global:LASTEXITCODE = 0
  & $Command
  $stepExitCode = $LASTEXITCODE
  if ($stepExitCode -ne 0) {
    throw "$Name failed with exit code $stepExitCode"
  }
}

function Assert-Exists {
  param([Parameter(Mandatory = $true)][string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) {
    throw "Required release artifact or file is missing: $Path"
  }
}

function Assert-NonEmptyFile {
  param([Parameter(Mandatory = $true)][string]$Path)
  Assert-Exists $Path
  $item = Get-Item -LiteralPath $Path
  if ($item.Length -le 0) {
    throw "Release artifact is empty: $Path"
  }
}

function Assert-ReleaseManifest {
  param([Parameter(Mandatory = $true)][string]$Dist)
  $expected = @($InstallerArtifact)
  foreach ($artifact in $expected) {
    Assert-NonEmptyFile (Join-Path $Dist $artifact)
  }
  $manifestPath = Join-Path $Dist "SHA256SUMS.txt"
  Assert-NonEmptyFile $manifestPath
  $lines = @(Get-Content -LiteralPath $manifestPath -Encoding UTF8 | Where-Object { $_.Trim() })
  if ($lines.Count -ne $expected.Count) {
    throw "SHA256SUMS.txt must contain exactly $($expected.Count) artifact lines."
  }
  foreach ($artifact in $expected) {
    $escaped = [regex]::Escape($artifact)
    if (-not ($lines | Where-Object { $_ -match "^[a-f0-9]{64}  $escaped$" })) {
      throw "SHA256SUMS.txt is missing a valid checksum line for $artifact"
    }
  }
  $rootFiles = @(Get-ChildItem -LiteralPath $Dist -File | Select-Object -ExpandProperty Name)
  $allowed = @($InstallerArtifact, "SHA256SUMS.txt")
  $extra = @($rootFiles | Where-Object { $_ -notin $allowed })
  if ($extra.Count -gt 0) {
    throw "Unexpected root release artifact(s): $($extra -join ', ')"
  }
}

function Assert-TextClean {
  param([Parameter(Mandatory = $true)][string]$Path)
  $text = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
  $markers = @(
    [string][char]0x00D0,
    [string][char]0x00D1,
    "$([char]0x00E2)$([char]0x20AC)$([char]0x201D)",
    "$([char]0x00E2)$([char]0x20AC)$([char]0x201C)"
  )
  foreach ($marker in $markers) {
    if ($text.Contains($marker)) {
      throw "Mojibake marker '$marker' found in $Path"
    }
  }
}

Invoke-Step "Python unit tests" {
  python -m unittest discover -s tests -p "test_*.py" -v
}

Invoke-Step "Config dry-run" {
  python best_isolator.py --dry-run
}

Invoke-Step "NPM dependency audit" {
  # Gate only on actionable runtime advisories: a low-severity advisory in a
  # dev-only transitive dependency must not turn unrelated changes red.
  npm --prefix ui audit --omit=dev --audit-level=high
}

Invoke-Step "Renderer build" {
  npm --prefix ui run build:renderer
}

Invoke-Step "Deterministic asset generation" {
  npm --prefix ui run build:assets
}

Invoke-Step "Backend manifest generation" {
  npm --prefix ui run build:backend-manifest
}

Invoke-Step "Tracked asset drift check" {
  git diff --exit-code -- ui/assets
}

Invoke-Step "Tracked backend manifest drift check" {
  git diff --exit-code -- ui/backend-manifest.json
}

Invoke-Step "UI smoke test" {
  npm --prefix ui run smoke
}

if (-not $SkipPackage) {
  $packageOutput = Join-Path $Root "ui/dist-packaged"
  Invoke-Step "Clean packaged output" {
    npm --prefix ui run clean:packaged
  }

  Invoke-Step "Windows package build" {
    npm --prefix ui run build
  }

  Invoke-Step "Packaged runtime provenance check" {
    npm --prefix ui run verify:packaged-runtime
  }

  $byproducts = @(
    (Join-Path $packageOutput "$InstallerArtifact.blockmap"),
    (Join-Path $packageOutput "builder-debug.yml")
  )
  foreach ($item in $byproducts) {
    if (Test-Path -LiteralPath $item) {
      node ui/scripts/clean-packaged-output.js $item
    }
  }

  Invoke-Step "Release checksum manifest" {
    powershell -File scripts/release-manifest.ps1
  }

  Assert-ReleaseManifest $packageOutput

  Invoke-Step "Installed artifact verification" {
    # EII_RELEASE_DEV_SKIP_INSTALLED_ARTIFACT_VERIFY=1 is an explicit local
    # development escape hatch handled by the verifier; release builds run it.
    npm --prefix ui run verify:installed-artifacts
  }

  $winUnpacked = Join-Path $packageOutput "win-unpacked"
  if (Test-Path -LiteralPath $winUnpacked) {
    node ui/scripts/clean-packaged-output.js $winUnpacked
  }
}

Write-Host "`n== Public surface checks ==" -ForegroundColor Cyan
$requiredFiles = @(
  "README.md",
  "BUILDING.md",
  "CONTRIBUTING.md",
  "SECURITY.md",
  "docs/oss-launch-checklist.md",
  "docs/release-readiness.md",
  "docs/benchmarks/cs2-vprof-summary.json",
  ".github/ISSUE_TEMPLATE/bug_report.yml",
  ".github/ISSUE_TEMPLATE/benchmark_report.md",
  ".github/pull_request_template.md",
  "docs/screenshots/dashboard.png",
  "docs/screenshots/topology.png",
  "docs/screenshots/settings.png"
)

foreach ($file in $requiredFiles) {
  Assert-Exists $file
}

foreach ($file in @("README.md", "BUILDING.md", "CONTRIBUTING.md", "SECURITY.md", "docs/oss-launch-checklist.md", "docs/release-readiness.md", "ui/src/i18n.jsx")) {
  Assert-TextClean $file
}

Write-Host "`n== Git ignore safety checks ==" -ForegroundColor Cyan
git check-ignore config.json *.log jail_state.json jail_state.json.tmp recovery_state.json recovery_state.json.tmp ui/dist-packaged
if ($LASTEXITCODE -ne 0) {
  throw "Expected local config/log/recovery/package artifacts to be ignored"
}

Write-Host "`nRelease readiness gate passed." -ForegroundColor Green
