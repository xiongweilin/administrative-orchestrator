#Requires -Version 7.0
[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
param(
    [Parameter(Mandatory)]
    [string]$ArchivePath,

    [string]$TargetVolumeName = 'administrative-m7-staging_administrative-m7-intake-artifacts-restore'
)

$ErrorActionPreference = 'Stop'
$resolvedArchive = (Resolve-Path -LiteralPath $ArchivePath -ErrorAction Stop).Path
if ($TargetVolumeName -eq 'administrative-m7-staging_administrative-m7-intake-artifacts') {
    throw 'Refusing to restore into the live staging artifact volume.'
}
if ($TargetVolumeName -notmatch '^[a-zA-Z0-9][a-zA-Z0-9_.-]*$') {
    throw 'TargetVolumeName contains unsupported characters.'
}

$existing = docker volume inspect $TargetVolumeName 2>$null
if ($LASTEXITCODE -eq 0 -and $existing) {
    throw "Target volume already exists; choose a new isolated volume: $TargetVolumeName"
}

$archiveDirectory = Split-Path -Parent $resolvedArchive
$archiveName = Split-Path -Leaf $resolvedArchive
if ($PSCmdlet.ShouldProcess($TargetVolumeName, 'Create isolated artifact restore volume')) {
    docker volume create $TargetVolumeName | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw 'Failed to create isolated restore volume.'
    }

    docker run --rm `
        --mount "type=volume,source=$TargetVolumeName,target=/restore" `
        --mount "type=bind,source=$archiveDirectory,target=/backup,readonly" `
        alpine:3.20 `
        sh -c "tar -xzf /backup/$archiveName -C /restore"
    if ($LASTEXITCODE -ne 0) {
        throw 'Artifact archive restore failed.'
    }

    docker run --rm `
        --mount "type=volume,source=$TargetVolumeName,target=/restore,readonly" `
        alpine:3.20 `
        sh -c 'find /restore/sha256 -type f | wc -l'
    if ($LASTEXITCODE -ne 0) {
        throw 'Isolated restore verification failed.'
    }
}
