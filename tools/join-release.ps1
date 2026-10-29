param([Parameter(Mandatory=$true)][string]$Manifest)
$ErrorActionPreference = 'Stop'
$manifestPath = (Resolve-Path -LiteralPath $Manifest).Path
$basePath = [System.IO.Path]::GetDirectoryName($manifestPath)
$info = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
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
    if ((Get-FileHash -LiteralPath $partPath -Algorithm SHA256).Hash -ne $part.sha256) { throw "Checksum mismatch: $($part.name)" }
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
if ((Get-FileHash -LiteralPath $outputPath -Algorithm SHA256).Hash -ne $info.sha256) {
    throw "Combined ZIP checksum mismatch. Do not extract: $outputPath"
}
Write-Output "Verified: $outputPath"
