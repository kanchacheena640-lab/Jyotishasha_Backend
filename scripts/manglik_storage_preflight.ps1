param([Parameter(Mandatory=$true)][string]$Directory)
$ErrorActionPreference = 'Stop'
try {
    $item = Get-Item -LiteralPath $Directory
    if (-not $item.PSIsContainer) { throw 'directory_required' }
    $current = $item
    while ($null -ne $current) {
        if (($current.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'reparse_point' }
        $current = $current.Parent
    }
    $volume = Get-BitLockerVolume -MountPoint ([IO.Path]::GetPathRoot($item.FullName))
    if ($volume.ProtectionStatus -ne 'On' -or $volume.VolumeStatus -ne 'FullyEncrypted') { throw 'encryption_required' }
    $acl = Get-Acl -LiteralPath $item.FullName
    $operatorSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $ownerSid = $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value
    if (-not $acl.AreAccessRulesProtected -or $ownerSid -ne $operatorSid) { throw 'acl_owner_or_inheritance' }
    $allowed = @($operatorSid, 'S-1-5-18', 'S-1-5-32-544')
    $operatorCanReadWrite = $false
    foreach ($rule in $acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])) {
        if ($rule.AccessControlType -eq 'Allow' -and $rule.IdentityReference.Value -notin $allowed) { throw 'broad_acl' }
        if ($rule.AccessControlType -eq 'Deny') { throw 'deny_acl_requires_review' }
        if ($rule.IdentityReference.Value -eq $operatorSid -and $rule.AccessControlType -eq 'Allow' -and
            (($rule.FileSystemRights -band [Security.AccessControl.FileSystemRights]::Modify) -eq [Security.AccessControl.FileSystemRights]::Modify) -and
            (($rule.InheritanceFlags -band [Security.AccessControl.InheritanceFlags]::ObjectInherit) -ne 0)) { $operatorCanReadWrite = $true }
    }
    if (-not $operatorCanReadWrite) { throw 'operator_file_rights' }
    foreach ($file in Get-ChildItem -LiteralPath $item.FullName -Force) {
        if ($file.PSIsContainer -or ($file.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'nested_or_reparse_entry' }
        $fileAcl = Get-Acl -LiteralPath $file.FullName
        if ($fileAcl.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $operatorSid) { throw 'file_owner' }
        foreach ($rule in $fileAcl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])) {
            if ($rule.AccessControlType -eq 'Allow' -and $rule.IdentityReference.Value -notin $allowed) { throw 'file_broad_acl' }
            if ($rule.AccessControlType -eq 'Deny') { throw 'file_deny_acl' }
        }
    }
    '{"encrypted":true,"restricted_acl":true,"no_reparse_points":true}'
} catch {
    Write-Output '{"encrypted":false,"restricted_acl":false,"no_reparse_points":false}'
    exit 1
}
