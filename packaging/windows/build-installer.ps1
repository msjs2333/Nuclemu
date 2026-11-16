# Package a previously built offline directory; never installs on the build host.
param(
    [Parameter(Mandatory)] [string]$Compiler,
    [string]$PayloadDirectory = "$PSScriptRoot/../../dist/Nuclemu",
    [string]$OutputDirectory = "$PSScriptRoot/../../dist/release",
    [string]$Version = '0.0.1'
)
$ErrorActionPreference = 'Stop'
$compilerPath = (Resolve-Path -LiteralPath $Compiler).Path
$payload = (Resolve-Path -LiteralPath $PayloadDirectory).Path
foreach ($required in 'nuclemu.exe','Nuclemu-Desktop.exe','_internal/licenses/Nuclemu/LICENSE','_internal/nuclemu/static/nuclemu.ico') {
    if (!(Test-Path -LiteralPath (Join-Path $payload $required) -PathType Leaf)) { throw "Missing payload: $required" }
}
if ($Version -notmatch '^\d+\.\d+\.\d+(?:\.\d+)?$') { throw 'Version must have three or four numeric components' }
$output = (New-Item -ItemType Directory -Force -Path $OutputDirectory).FullName
$temporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$work = Join-Path $temporaryRoot ('NuclemuInstaller-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $work | Out-Null
try {
    $staged = Join-Path $work 'payload'
    Copy-Item -LiteralPath $payload -Destination $staged -Recurse
    Copy-Item -LiteralPath "$PSScriptRoot/README.md" -Destination "$staged/README.md" -Force
    Copy-Item -LiteralPath "$PSScriptRoot/THIRD-PARTY.md","$PSScriptRoot/Inno-Setup-LICENSE.txt" -Destination $staged -Force
    $payload = $staged
    $ledger = Join-Path $work 'payload-files.txt'
    Get-ChildItem -LiteralPath $payload -File -Recurse | Sort-Object FullName |
        ForEach-Object { $_.FullName.Substring($payload.Length + 1) } |
        Set-Content -LiteralPath $ledger -Encoding UTF8
    & $compilerPath "/DPayloadDir=$payload" "/DReleaseDir=$work" "/DAppVersion=$Version" "/DPayloadManifest=$ledger" "$PSScriptRoot/installer.iss"
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup compiler failed: $LASTEXITCODE" }
    $name = "Nuclemu-$Version-windows-x64-setup.exe"
    Copy-Item -LiteralPath (Join-Path $work $name) -Destination (Join-Path $output $name) -Force
    $files = @(Get-ChildItem -LiteralPath $payload -File -Recurse | Sort-Object FullName | ForEach-Object {
        @{path=$_.FullName.Substring($payload.Length + 1).Replace('\','/');
          bytes=$_.Length; sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}
    })
    $manifest = @{version=$Version; built_utc=[DateTime]::UtcNow.ToString('o');
        compiler_file_version=(Get-Item -LiteralPath $compilerPath).VersionInfo.FileVersion;
        compiler_sha256=(Get-FileHash -LiteralPath $compilerPath).Hash.ToLowerInvariant();
        installer=$name; sha256=(Get-FileHash -LiteralPath (Join-Path $output $name)).Hash.ToLowerInvariant(); payload=$files}
    $manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $output "$name.manifest.json") -Encoding UTF8
    Get-FileHash -LiteralPath (Join-Path $output $name) -Algorithm SHA256
} finally {
    # This is always our fresh child of the OS temporary directory.
    $resolved = [IO.Path]::GetFullPath($work)
    if (!$resolved.StartsWith($temporaryRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid temporary build path' }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}
