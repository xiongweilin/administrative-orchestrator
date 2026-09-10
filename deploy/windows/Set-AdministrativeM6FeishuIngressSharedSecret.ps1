#Requires -Version 7.0
[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
param(
    [ValidateSet('generate-and-materialize', 'materialize')]
    [string]$Command = 'generate-and-materialize',

    [string]$AdminOutputPath = 'D:\infrastructure\compose\administrative-orchestrator\deploy\m6-staging\.env.m6-secrets',

    [string]$GatewayVolumeName = 'feishu_secrets',

    [string]$GatewaySecretFileName = 'administrative_ingress_shared_secret',

    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$credentialName = 'Agent:Metratio:AdministrativeM6FeishuIngressSharedSecret'

if (-not ('AdministrativeM6IngressSecret.NativeMethods' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

namespace AdministrativeM6IngressSecret {
    public static class NativeMethods {
        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        public struct CREDENTIAL {
            public uint Flags;
            public uint Type;
            public string TargetName;
            public string Comment;
            public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten;
            public uint CredentialBlobSize;
            public IntPtr CredentialBlob;
            public uint Persist;
            public uint AttributeCount;
            public IntPtr Attributes;
            public string TargetAlias;
            public string UserName;
        }

        [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        public static extern bool CredRead(string target, uint type, uint flags, out IntPtr credential);

        [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        public static extern bool CredWrite(ref CREDENTIAL credential, uint flags);

        [DllImport("advapi32.dll", SetLastError = true)]
        public static extern void CredFree(IntPtr buffer);
    }
}
'@
}

function Read-SharedSecret {
    $pointer = [IntPtr]::Zero
    if (-not [AdministrativeM6IngressSecret.NativeMethods]::CredRead($credentialName, 1, 0, [ref]$pointer)) {
        throw "Credential is not configured: $credentialName"
    }
    try {
        $credential = [Runtime.InteropServices.Marshal]::PtrToStructure(
            $pointer,
            [type][AdministrativeM6IngressSecret.NativeMethods+CREDENTIAL]
        )
        if ($credential.CredentialBlobSize -eq 0) {
            throw 'Credential value is empty.'
        }
        return [Runtime.InteropServices.Marshal]::PtrToStringUni(
            $credential.CredentialBlob,
            [int]($credential.CredentialBlobSize / 2)
        )
    }
    finally {
        [AdministrativeM6IngressSecret.NativeMethods]::CredFree($pointer)
    }
}

function Write-SharedSecret {
    param([Parameter(Mandatory)] [Security.SecureString]$SecureValue)

    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToCoTaskMemUnicode($SecureValue)
    try {
        $bytes = [uint32]($SecureValue.Length * 2)
        if ($bytes -eq 0) { throw 'Credential value cannot be empty.' }
        $credential = [AdministrativeM6IngressSecret.NativeMethods+CREDENTIAL]::new()
        $credential.Type = 1
        $credential.TargetName = $credentialName
        $credential.Comment = 'Administrative M6 gateway transport secret; task-scoped materialization only.'
        $credential.CredentialBlobSize = $bytes
        $credential.CredentialBlob = $pointer
        $credential.Persist = 2
        $credential.UserName = 'administrative-m6-gateway'
        if (-not [AdministrativeM6IngressSecret.NativeMethods]::CredWrite([ref]$credential, 0)) {
            throw [ComponentModel.Win32Exception]::new(
                [Runtime.InteropServices.Marshal]::GetLastWin32Error()
            )
        }
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeCoTaskMemUnicode($pointer)
    }
}

function New-SharedSecret {
    $bytes = New-Object byte[] 32
    [Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

function Write-AdminEnvironment {
    param([Parameter(Mandatory)] [string]$Secret)

    $resolved = [System.IO.Path]::GetFullPath($AdminOutputPath)
    $parent = [System.IO.Path]::GetDirectoryName($resolved)
    if ([string]::IsNullOrWhiteSpace($parent)) { throw 'AdminOutputPath must have a directory.' }
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    if ((Test-Path -LiteralPath $resolved) -and -not $Force) {
        throw "Admin output already exists; use -Force for an intentional task-scoped update: $resolved"
    }
    $lines = if (Test-Path -LiteralPath $resolved) {
        [IO.File]::ReadAllLines($resolved)
    } else {
        @()
    }
    $kept = @($lines | Where-Object { $_ -notmatch '^ADMIN_FEISHU_INGRESS_SHARED_SECRET=' })
    $kept += "ADMIN_FEISHU_INGRESS_SHARED_SECRET=$Secret"
    if ($PSCmdlet.ShouldProcess($resolved, 'Materialize M6 gateway transport secret reference')) {
        [IO.File]::WriteAllLines($resolved, $kept, [Text.UTF8Encoding]::new($false))
        $principal = "$env:USERDOMAIN\$env:USERNAME"
        & icacls.exe $resolved /inheritance:r /grant:r "${principal}:(R,W)" *> $null
        if ($LASTEXITCODE -ne 0) { throw 'Failed to restrict task-scoped env file permissions.' }
    }
}

function Write-GatewayVolumeSecret {
    param([Parameter(Mandatory)] [string]$Secret)

    if ($GatewayVolumeName -notmatch '^[A-Za-z0-9_.-]+$') {
        throw 'GatewayVolumeName contains unsupported characters.'
    }
    if ($GatewaySecretFileName -notmatch '^[A-Za-z0-9_.-]+$') {
        throw 'GatewaySecretFileName contains unsupported characters.'
    }
    if (-not $PSCmdlet.ShouldProcess(
        "$GatewayVolumeName/$GatewaySecretFileName",
        'Materialize gateway transport secret into the external secret volume'
    )) { return }

    $mount = "type=volume,source=$GatewayVolumeName,target=/run/secrets"
    $command = "umask 077; cat > /run/secrets/$GatewaySecretFileName; chown 10001:10001 /run/secrets/$GatewaySecretFileName; test -s /run/secrets/$GatewaySecretFileName"
    $payload = $Secret + "`n"
    $payload | & docker run --rm -i --network none --mount $mount postgres:17-alpine sh -c $command *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Gateway secret volume materialization failed with exit code $LASTEXITCODE."
    }
}

if ($Command -eq 'generate-and-materialize') {
    $plain = New-SharedSecret
    try {
        $secure = ConvertTo-SecureString -String $plain -AsPlainText -Force
        Write-SharedSecret -SecureValue $secure
        $secure = $null
    }
    finally {
        $plain = $null
    }
}

$secret = Read-SharedSecret
try {
    if ($secret -match '[\r\n]' -or [string]::IsNullOrWhiteSpace($secret)) {
        throw 'Credential value is empty or contains a line break.'
    }
    Write-AdminEnvironment -Secret $secret
    Write-GatewayVolumeSecret -Secret $secret
    'Administrative M6 gateway transport secret materialized. No value was displayed.'
}
finally {
    $secret = $null
}
