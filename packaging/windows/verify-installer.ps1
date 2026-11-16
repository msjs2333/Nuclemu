# Run only inside a disposable Windows test machine, never on the build host.
param(
    [Parameter(Mandatory)] [string]$ExpectedComputerName,
    [Parameter(Mandatory)] [ValidateSet('CurrentUser','AllUsers')] [string]$Mode,
    [Parameter(Mandatory)] [string]$Setup,
    [Parameter(Mandatory)] [string]$PreviousSetup,
    [Parameter(Mandatory)] [string]$FixtureDirectory,
    [Parameter(Mandatory)] [string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
if ($env:COMPUTERNAME -ne $ExpectedComputerName) { throw 'Wrong test machine; refusing installation' }
$out = (New-Item -ItemType Directory -Path $OutputDirectory -ErrorAction Stop).FullName
Start-Transcript -Path "$out/transcript.txt" | Out-Null
$setupPath = (Resolve-Path -LiteralPath $Setup).Path
$previousPath = (Resolve-Path -LiteralPath $PreviousSetup).Path
$app = if ($Mode -eq 'AllUsers') { Join-Path $env:ProgramFiles '核物理 课堂\Nuclemu' }
       else { Join-Path $env:LOCALAPPDATA 'Programs\核物理 课堂\Nuclemu' }
$registryRoot = if ($Mode -eq 'AllUsers') { 'HKLM:' } else { 'HKCU:' }
$key = "$registryRoot\Software\Microsoft\Windows\CurrentVersion\Uninstall\{EDDB3BC4-699D-4824-BF85-4FE3A3B2A326}_is1"
$shortcutRoot = if ($Mode -eq 'AllUsers') { "$env:ProgramData\Microsoft\Windows\Start Menu\Programs" }
                else { "$env:APPDATA\Microsoft\Windows\Start Menu\Programs" }
$shortcut = Join-Path $shortcutRoot 'Nuclemu.lnk'
$scope = if ($Mode -eq 'AllUsers') { '/ALLUSERS' } else { '/CURRENTUSER' }
function Install($file, $label, $first=$false) {
    $arguments = @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-','/LANG=chinesesimp',"/LOG=`"$out/$label.log`"")
    if ($first) {
        $arguments += "/DIR=`"$app`""
        if ($Mode -eq 'AllUsers') { $arguments += $scope }
    }
    $p = Start-Process -FilePath $file -ArgumentList $arguments -PassThru -WindowStyle Hidden -Wait
    if ($p.ExitCode -ne 0) { throw "$label failed: $($p.ExitCode)" }
}
function Assert-Installed($version) {
    $entry = Get-ItemProperty -LiteralPath $key
    if ($entry.DisplayVersion -ne $version -or $entry.InstallLocation.TrimEnd('\') -ne $app) { throw 'Scope, version or previous directory not preserved' }
    if (!(Test-Path -LiteralPath $shortcut)) { throw 'Missing Start menu shortcut' }
    $shell = New-Object -ComObject Shell.Application
    $link = $shell.Namespace($shortcutRoot).ParseName('Nuclemu.lnk').GetLink
    $target = [Environment]::ExpandEnvironmentVariables($link.Path)
    $working = [Environment]::ExpandEnvironmentVariables($link.WorkingDirectory)
    Write-Output "Start menu shortcut: target=[$target], working directory=[$working], install=[$app]"
    if ($target -ne "$app\Nuclemu-Desktop.exe" -or $working.TrimEnd('\') -ne $app) {
        throw 'Shortcut target or shared working directory is wrong'
    }
    & "$app/nuclemu.exe" validate
    if ($LASTEXITCODE -ne 0) { throw 'Installed catalog failed' }
}
function Profile-Hashes {
    @(Get-ChildItem -LiteralPath "$env:USERPROFILE/.nuclemu" -File -Recurse | Sort-Object FullName |
      ForEach-Object { $_.FullName + ':' + (Get-FileHash -LiteralPath $_.FullName).Hash })
}
function Check-Fixtures {
    foreach ($name in 'AEL','BABS') {
        $file = Join-Path $data "$name.nuclemu"
        & "$app/nuclemu.exe" files inspect $file | Out-File "$out/$name-inspect.json" -Encoding UTF8
        if ($LASTEXITCODE -ne 0) { throw "Fixture cannot reopen: $name" }
        if ((Get-FileHash -LiteralPath $file).Hash -ne $fixtureHashes[$name]) { throw "Fixture changed: $name" }
    }
}
try {
    whoami /all | Out-File "$out/account.txt"
    $identity = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
    $admin = $identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if ($Mode -eq 'CurrentUser' -and $admin) { throw 'Current-user acceptance must run as an actual non-administrator' }
    if ($Mode -eq 'AllUsers' -and !$admin) { throw 'Machine acceptance requires an administrator' }
    Install $previousPath 'old-install' $true
    Assert-Installed '0.0.0'
    if (!(Test-Path "$app/obsolete-runtime.txt")) { throw 'Old fixture lacks obsolete tracked file' }
    $data = (New-Item -ItemType Directory -Force "$env:USERPROFILE/Documents/实验 文件").FullName
    $fixtureHashes = @{}
    foreach ($name in 'AEL','BABS') {
        Copy-Item -LiteralPath (Join-Path $FixtureDirectory "$name.nuclemu") -Destination $data
        $fixtureHashes[$name] = (Get-FileHash -LiteralPath (Join-Path $data "$name.nuclemu")).Hash
    }
    & "$PSScriptRoot/smoke.ps1" -Executable "$app/nuclemu.exe" -OutputDirectory "$out/old-smoke"
    $preferences = "$env:USERPROFILE/.nuclemu/launcher.json"
    New-Item -ItemType Directory -Force (Split-Path $preferences) | Out-Null
    [IO.File]::WriteAllText($preferences, '{"port":54321,"open_browser":false}', [Text.UTF8Encoding]::new($false))
    Copy-Item -LiteralPath "$data/AEL.nuclemu" -Destination "$app/student-file.nuclemu"
    $before = Profile-Hashes
    Check-Fixtures
    Install $setupPath 'upgrade' # Deliberately omit scope and directory.
    Assert-Installed '0.0.1'
    if (Test-Path "$app/obsolete-runtime.txt") { throw 'Obsolete tracked program file survived upgrade' }
    if (!(Test-Path "$app/student-file.nuclemu")) { throw 'Untracked user file removed during upgrade' }
    if (($before -join '|') -ne ((Profile-Hashes) -join '|')) { throw 'Profile files changed during upgrade' }
    Check-Fixtures
    & "$PSScriptRoot/smoke.ps1" -Executable "$app/nuclemu.exe" -OutputDirectory "$out/new-smoke"
    $gui = Start-Process -FilePath $shortcut -PassThru -WindowStyle Hidden
    $deadline = (Get-Date).AddSeconds(20)
    do {
        try { $catalog = Invoke-RestMethod 'http://127.0.0.1:54321/api/catalog'; break } catch { }
        if ($gui.HasExited -or (Get-Date) -gt $deadline) { throw 'Installed Start menu GUI did not become ready' }
        Start-Sleep -Milliseconds 100
    } while ($true)
    if ('alpha' -notin $catalog.experiments.id -or 'beta' -notin $catalog.experiments.id) { throw 'GUI installed catalog missing' }
    $second = Start-Process "$app/nuclemu.exe" -ArgumentList 'serve','--gui' -WindowStyle Hidden -PassThru
    if (!$second.WaitForExit(5000) -or $second.ExitCode -ne 0 -or $gui.HasExited) { throw 'Second GUI entry did not reuse installed instance' }
    $gui.Refresh()
    if ($gui.MainWindowHandle -eq 0 -or $gui.MainWindowTitle -ne 'Nuclemu') { throw 'Installed GUI semantic window is missing' }
    $programHash = (Get-FileHash -LiteralPath "$app/Nuclemu-Desktop.exe").Hash
    $blocked = Start-Process $setupPath -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',"/LOG=`"$out/running-update.log`"" -WindowStyle Hidden -PassThru -Wait
    if ($blocked.ExitCode -eq 0 -or $gui.HasExited) { throw 'Update did not protect running application' }
    $blocked = Start-Process "$app/unins000.exe" -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',"/LOG=`"$out/running-uninstall.log`"" -WindowStyle Hidden -PassThru -Wait
    if ($blocked.ExitCode -eq 0 -or $gui.HasExited -or (Get-FileHash -LiteralPath "$app/Nuclemu-Desktop.exe").Hash -ne $programHash) { throw 'Uninstall did not protect running application' }
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class InstallerTestWindow {
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr window, uint message, IntPtr a, IntPtr b);
}
'@
    [void][InstallerTestWindow]::PostMessage($gui.MainWindowHandle, 0x10, [IntPtr]::Zero, [IntPtr]::Zero)
    if (!$gui.WaitForExit(5000) -or $gui.ExitCode -ne 0) { throw 'Installed idle GUI did not close' }
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,54321)
    try { $listener.Start() } finally { $listener.Stop() }
    $beforeUninstall = Profile-Hashes
    $uninstaller = Join-Path $app 'unins000.exe'
    $p = Start-Process $uninstaller -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',"/LOG=`"$out/uninstall.log`"") -WindowStyle Hidden -PassThru -Wait
    if ($p.ExitCode -ne 0) { throw "Uninstall failed: $($p.ExitCode)" }
    if ((Test-Path $key) -or (Test-Path $shortcut) -or (Test-Path "$app/nuclemu.exe")) { throw 'Uninstall registration or program files remain' }
    if (!(Test-Path "$app/student-file.nuclemu")) { throw 'Uninstall removed untracked user file' }
    if (($beforeUninstall -join '|') -ne ((Profile-Hashes) -join '|')) { throw 'Uninstall changed retained workbench/profile files' }
    if ((Get-Content -LiteralPath $preferences -Raw) -ne '{"port":54321,"open_browser":false}') { throw 'Preferences lost on uninstall' }
    foreach ($name in 'AEL','BABS') {
        if ((Get-FileHash -LiteralPath "$data/$name.nuclemu").Hash -ne $fixtureHashes[$name]) { throw 'Saved user experiment lost on uninstall' }
    }
    # Reinstall after uninstall and reopen the retained user files and settings.
    Install $setupPath 'reinstall' $true
    Assert-Installed '0.0.1'
    Check-Fixtures
    $p = Start-Process "$app/unins000.exe" -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART' -WindowStyle Hidden -PassThru -Wait
    if ($p.ExitCode -ne 0) { throw 'Final uninstall failed' }
    @{result='PASS'; mode=$Mode; actual_admin=$admin; user=$env:USERNAME; computer=$env:COMPUTERNAME;
      os=[Environment]::OSVersion.VersionString; app=$app; shortcut=$shortcut; files=$fixtureHashes;
      setup_sha256=(Get-FileHash -LiteralPath $setupPath).Hash; utc=[DateTime]::UtcNow.ToString('o')} |
        ConvertTo-Json -Depth 5 | Set-Content "$out/result.json" -Encoding UTF8
} catch {
    ($_ | Out-String) + $_.ScriptStackTrace | Set-Content "$out/ERROR.txt"
    throw
} finally {
    Stop-Transcript | Out-Null
}
