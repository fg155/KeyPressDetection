@echo off
setlocal
set "KPD_JOIN_SCRIPT=%~f0"
set "KPD_JOIN_MANIFEST=%~1"
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $text=[IO.File]::ReadAllText($env:KPD_JOIN_SCRIPT); $marker='# POWERSHELL_PAYLOAD'; & ([scriptblock]::Create($text.Substring($text.LastIndexOf($marker)+$marker.Length))) -Manifest $env:KPD_JOIN_MANIFEST -ScriptPath $env:KPD_JOIN_SCRIPT } catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }"
set "KPD_JOIN_EXIT=%errorlevel%"
if not "%KPD_JOIN_EXIT%"=="0" pause
exit /b %KPD_JOIN_EXIT%
# POWERSHELL_PAYLOAD
param([string]$Manifest,[string]$ScriptPath)
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($Manifest)) {
    $candidates = @(Get-ChildItem -LiteralPath ([IO.Path]::GetDirectoryName($ScriptPath)) -Filter '*.parts.json' -File)
    if ($candidates.Count -ne 1) { throw 'Place exactly one .parts.json manifest beside this script, or drag the desired manifest onto this script.' }
    $Manifest = $candidates[0].FullName
}
$manifestPath = (Resolve-Path -LiteralPath $Manifest).Path
$basePath = [System.IO.Path]::GetDirectoryName($manifestPath)
$info = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
function Get-ReleaseHash([string]$path) {
    $stream = [System.IO.File]::OpenRead($path)
    $algorithm = [System.Security.Cryptography.SHA256]::Create()
    try { return [System.BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-','') }
    finally { $algorithm.Dispose(); $stream.Dispose() }
}
function Resolve-ReleaseFile([string]$name) {
    if ([string]::IsNullOrWhiteSpace($name) -or $name -ne [System.IO.Path]::GetFileName($name) -or $name.IndexOfAny([System.IO.Path]::GetInvalidFileNameChars()) -ge 0) {
        throw "Invalid release filename: $name"
    }
    return [System.IO.Path]::Combine($basePath,$name)
}
$outputPath = Resolve-ReleaseFile $info.file
if (Test-Path -LiteralPath $outputPath) { throw 'The output ZIP already exists. Nothing was overwritten.' }
if (-not $info.parts -or -not $info.sha256 -or $info.bytes -lt 1) { throw 'Invalid release manifest.' }
$partPaths = @()
$totalBytes = 0L
foreach ($part in $info.parts) {
    $partPath = Resolve-ReleaseFile $part.name
    $item = Get-Item -LiteralPath $partPath
    if ($item.Length -ne $part.bytes) { throw "Size mismatch: $($part.name)" }
    if ((Get-ReleaseHash $partPath) -ne $part.sha256) { throw "Checksum mismatch: $($part.name)" }
    $partPaths += $partPath
    $totalBytes += $item.Length
}
if ($totalBytes -ne $info.bytes) { throw 'Total size does not match the manifest.' }
$outputStream = [System.IO.File]::Open($outputPath,[System.IO.FileMode]::CreateNew,[System.IO.FileAccess]::Write)
try {
    foreach ($partPath in $partPaths) {
        $partStream = [System.IO.File]::OpenRead($partPath)
        try { $partStream.CopyTo($outputStream) } finally { $partStream.Dispose() }
    }
} finally { $outputStream.Dispose() }
if ((Get-ReleaseHash $outputPath) -ne $info.sha256) {
    throw "Combined ZIP checksum mismatch. Do not extract: $outputPath"
}
Write-Output "Verified: $outputPath"
