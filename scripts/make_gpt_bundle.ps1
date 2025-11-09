#!/usr/bin/env pwsh
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ——— Settings (overridable via .gpt-bundle.json) ———
$DefaultName = Split-Path -Leaf (Get-Location)
$MaxMBDefault = 5

function Has-Git { return [bool](Get-Command git -ErrorAction SilentlyContinue) }
function Has-Jq  { return [bool](Get-Command jq  -ErrorAction SilentlyContinue) }
function Timestamp { return (Get-Date).ToString("yyyyMMdd-HHmmss") }

# Load config
$Name    = $DefaultName
$MaxMB   = $MaxMBDefault
$Include = @()
$Exclude = @()

$HasConfig = Test-Path ".gpt-bundle.json"
$IsFile    = $HasConfig -and -not (Get-Item ".gpt-bundle.json").PSIsContainer

if ($IsFile) {
  if (Has-Jq) {
    # existing jq path...
  } else {
    try {
      $cfg = Get-Content ".gpt-bundle.json" -Raw | ConvertFrom-Json
      if ($cfg.name) { $Name = $cfg.name }
      if ($cfg.maxFileMB) { $MaxMB = [int]$cfg.maxFileMB }
      if ($cfg.includeGlobs) { $Include = @($cfg.includeGlobs) }
      if ($cfg.excludeGlobs) { $Exclude = @($cfg.excludeGlobs) }
    } catch {
      Write-Warning "Failed to parse .gpt-bundle.json without jq; using defaults."
    }
  }
}


if ($Include.Count -eq 0) { $Include = @("**/*") }
if ($Exclude.Count -eq 0) {
  $Exclude = @(
    "venv/**", ".venv/**", "node_modules/**", "dist/**", "build/**",
    "__pycache__/**", "**/*.pyc", "**/*.pyo", ".git/**", ".idea/**", ".vscode/**",
    "migrations/**", "media/**", "staticfiles/**",
    "**/*.zip", "**/*.7z", "**/*.tar", "**/*.tar.gz", "**/*.tgz",
    "*.pem", "*.key", "*.pfx", "*.p12", "*.crt", "*.env", ".env", ".env.*",
    "*.log", "*.bak", "*.tmp", "*.swp", ".DS_Store",
    "**/*.png", "**/*.jpg", "**/*.jpeg", "**/*.gif", "**/*.mp4", "**/*.mov"
  )
}

# Merge .gpt-bundle-ignore
if (Test-Path ".gpt-bundle-ignore" -PathType Leaf) {
  $extra = Get-Content ".gpt-bundle-ignore" | Where-Object { $_ -and -not $_.StartsWith("#") }
  $Exclude += $extra
}

$Dist = "dist"
New-Item -ItemType Directory -Force -Path $Dist | Out-Null

$Stamp = Timestamp
$OutBase = "${Name}_gpt_bundle_${Stamp}"
$Zip = Join-Path $Dist "$OutBase.zip"
$Manifest = Join-Path $Dist "$OutBase.manifest.txt"

# Get candidate files
$Files = @()
if (Has-Git) {
  try {
    git rev-parse --is-inside-work-tree *> $null
    $tracked   = git ls-files
    $untracked = git ls-files --others --exclude-standard
    $Files = $tracked + $untracked
  } catch {}
}
if (-not $Files -or $Files.Count -eq 0) {
  $Files = Get-ChildItem -Recurse -File | ForEach-Object { $_.FullName.Substring((Get-Location).Path.Length + 1) }
}

function Match-AnyGlob([string]$Path, [string[]]$Globs) {
  foreach ($g in $Globs) {
    if ([System.Management.Automation.WildcardPattern]::new($g, 'IgnoreCase').IsMatch($Path)) { return $true }
  }
  return $false
}

$MaxBytes = $MaxMB * 1MB
$Cand = New-Object System.Collections.Generic.List[string]
foreach ($f in $Files) {
  if (-not (Test-Path $f -PathType Leaf)) { continue }
  if (-not (Match-AnyGlob $f $Include)) { continue }
  if (Match-AnyGlob $f $Exclude) { continue }

  $info = Get-Item $f
  if ($info.Length -le $MaxBytes) {
    $Cand.Add($f)
  }
}

# Write manifest
$Branch = ""
$Commit = ""
$Dirty  = ""
if (Has-Git) {
  try { $Branch = git rev-parse --abbrev-ref HEAD } catch {}
  try { $Commit = git rev-parse --short HEAD } catch {}
  try { git diff --quiet; if ($LASTEXITCODE -ne 0) { $Dirty = "yes" } } catch {}
}

$PyVer = try { (python --version) 2>&1 } catch { "n/a" }
$NodeVer = try { (node --version) } catch { "n/a" }

@(
  "GPT Bundle Manifest"
  "-------------------"
  "Name:         $Name"
  "Timestamp:    $Stamp"
  "Git branch:   $Branch"
  "Git commit:   $Commit"
  ("Git dirty:    " + ($(if ($Dirty) { $Dirty } else { "no or unknown" })))
  "Python:       $PyVer"
  "Node:         $NodeVer"
  "Max file MB:  $MaxMB"
  ""
  "Included globs:"
  ($Include | ForEach-Object { "  - $_" })
  "Excluded globs:"
  ($Exclude | ForEach-Object { "  - $_" })
  ""
  "Files ($($Cand.Count)):"
  ($Cand | ForEach-Object { "  $_" })
) | Set-Content -Encoding UTF8 $Manifest

# Create ZIP
if (Test-Path $Zip) { Remove-Item $Zip -Force }
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zipArchive = [System.IO.Compression.ZipFile]::Open($Zip, 'Create')
try {
  foreach ($f in $Cand) {
    $abs = (Resolve-Path $f).Path
    $rel = $f -replace '^[.\\/]+',''
    [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zipArchive, $abs, $rel) | Out-Null
  }
  # include manifest
  [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zipArchive, (Resolve-Path $Manifest).Path, (Split-Path -Leaf $Manifest)) | Out-Null
} finally {
  $zipArchive.Dispose()
}

Write-Host "Created:"
Write-Host "  $Zip"
Write-Host "  $Manifest"
