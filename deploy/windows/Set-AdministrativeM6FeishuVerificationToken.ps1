#Requires -Version 7.0
[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
param(
    [ValidateSet('store', 'materialize', 'store-and-materialize')]
    [string]$Command = 'materialize',

    [string]$OutputPath = 'D:\infrastructure\compose\administrative-orchestrator\deploy\m6-staging\.env.m6-secrets',

    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$credentialName = 'Agent:Metratio:AdministrativeFeishuVerificationToken'

if (-not ('AdministrativeFeishuCredential.NativeMethods' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

namespace AdministrativeFeishuCredential {
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

function Read-VerificationToken {
    $pointer = [IntPtr]::Zero
    if (-not [AdministrativeFeishuCredential.NativeMethods]::CredRead($credentialName, 1, 0, [ref]$pointer)) {
        throw "Credential is not configured: $credentialName"
    }
    try {
        $credential = [Runtime.InteropServices.Marshal]::PtrToStructure(
            $pointer,
            [type][AdministrativeFeishuCredential.NativeMethods+CREDENTIAL]
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
        [AdministrativeFeishuCredential.NativeMethods]::CredFree($pointer)
    }
}

function Write-VerificationToken {
    param([Parameter(Mandatory)] [Security.SecureString]$SecureValue)

    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToCoTaskMemUnicode($SecureValue)
    try {
        $bytes = [uint32]($SecureValue.Length * 2)
        if ($bytes -eq 0) { throw 'Credential value cannot be empty.' }
        $credential = [AdministrativeFeishuCredential.NativeMethods+CREDENTIAL]::new()
        $credential.Type = 1
        $credential.TargetName = $credentialName
        $credential.Comment = 'Administrative M6 Feishu verification token; task-scoped materialization only.'
        $credential.CredentialBlobSize = $bytes
        $credential.CredentialBlob = $pointer
        $credential.Persist = 2
        $credential.UserName = 'administrative-m6'
        if (-not [AdministrativeFeishuCredential.NativeMethods]::CredWrite([ref]$credential, 0)) {
            throw [ComponentModel.Win32Exception]::new(
                [Runtime.InteropServices.Marshal]::GetLastWin32Error()
            )
        }
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeCoTaskMemUnicode($pointer)
    }
}

if ($Command -in @('store', 'store-and-materialize')) {
    $secureValue = Read-Host 'Enter the Feishu verification token' -AsSecureString
    Write-VerificationToken -SecureValue $secureValue
    $secureValue = $null
}

if ($Command -in @('materialize', 'store-and-materialize')) {
    if ([string]::IsNullOrWhiteSpace($OutputPath)) {
        throw 'OutputPath must not be blank.'
    }
    $resolvedOutput = [System.IO.Path]::GetFullPath($OutputPath)
    $parent = [System.IO.Path]::GetDirectoryName($resolvedOutput)
    if ([string]::IsNullOrWhiteSpace($parent)) {
        throw 'OutputPath must have a directory.'
    }
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    if ((Test-Path -LiteralPath $resolvedOutput) -and -not $Force) {
        throw "Output already exists; use -Force only for an intentional task-scoped replacement: $resolvedOutput"
    }

    $token = Read-VerificationToken
    if ($token -match '[\r\n]') {
        throw 'Credential value contains a line break and cannot be materialized into an env file.'
    }
    try {
        if ($PSCmdlet.ShouldProcess($resolvedOutput, 'Materialize task-scoped Feishu verification token env file')) {
            $encoding = [Text.UTF8Encoding]::new($false)
            [IO.File]::WriteAllText(
                $resolvedOutput,
                "ADMIN_FEISHU_VERIFICATION_TOKEN=$token`n",
                $encoding
            )
            $principal = "$env:USERDOMAIN\$env:USERNAME"
            & icacls.exe $resolvedOutput /inheritance:r /grant:r "${principal}:(R,W)" *> $null
            if ($LASTEXITCODE -ne 0) {
                throw 'Failed to restrict task-scoped env file permissions.'
            }
            'Administrative M6 Feishu verification token materialized. No value was displayed.'
        }
    }
    finally {
        $token = $null
    }
}
