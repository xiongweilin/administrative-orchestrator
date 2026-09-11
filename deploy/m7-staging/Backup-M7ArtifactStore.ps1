#Requires -Version 7.0
[CmdletBinding()]
param(
    [string]$VolumeName = 'administrative-m7-staging_administrative-m7-intake-artifacts',
    [string]$OutputDirectory = 'D:\infrastructure\compose\administrative-orchestrator\deploy\m7-staging\backups'
)

$ErrorActionPreference = 'Stop'
$resolvedOutput = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $resolvedOutput -Force | Out-Null

$volumeJson = docker volume inspect $VolumeName 2>$null
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace(($volumeJson -join ''))) {
    throw "Artifact volume was not found: $VolumeName"
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$archiveName = "m7-artifacts-$stamp.tar.gz"
$archivePath = Join-Path $resolvedOutput $archiveName
docker run --rm `
    --mount "type=volume,source=$VolumeName,target=/source,readonly" `
    --mount "type=bind,source=$resolvedOutput,target=/backup" `
    alpine:3.20 `
    sh -c "tar -czf /backup/$archiveName -C /source ."
if ($LASTEXITCODE -ne 0) {
    throw 'Artifact volume backup failed.'
}

if (-not (Test-Path -LiteralPath $archivePath -PathType Leaf)) {
    throw 'Artifact volume backup did not create an archive.'
}

Get-Item -LiteralPath $archivePath | Select-Object FullName, Length, LastWriteTimeUtc
