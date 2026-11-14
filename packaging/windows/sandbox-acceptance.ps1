# Orchestrate disposable-machine acceptance. Creates a standard account only there.
param([Parameter(Mandatory)] [string]$ExpectedComputerName)
$ErrorActionPreference = 'Stop'
if ($env:COMPUTERNAME -ne $ExpectedComputerName) { throw 'Wrong test machine; refusing account/install changes' }
$run = [guid]::NewGuid().ToString('N').Substring(0,6)
$work = 'C:\NuclemuInstallerAcceptance-' + $run
$evidence = (New-Item -ItemType Directory -Path ('C:\EvidenceOutput\run-' + $run)).FullName
trap { ($_ | Out-String) + $_.ScriptStackTrace | Set-Content "$evidence/driver-error.txt"; break }
if (Test-Path -LiteralPath $work) { throw 'Acceptance workspace already exists; use a fresh sandbox' }
New-Item -ItemType Directory -Path $work | Out-Null
Copy-Item -LiteralPath 'C:\NuclemuPackaging' -Destination "$work/scripts" -Recurse
Copy-Item -LiteralPath 'C:\NuclemuInput\samples' -Destination "$work/fixtures" -Recurse
Copy-Item -LiteralPath 'C:\ReleaseOutput\Nuclemu-0.0.1-windows-x64-setup.exe' -Destination "$work/current.exe"
Copy-Item -LiteralPath 'C:\BuildOutputs\Nuclemu-0.0.0-windows-x64-setup.exe' -Destination "$work/previous.exe"
& "$work/scripts/verify-installer.ps1" -ExpectedComputerName $ExpectedComputerName -Mode AllUsers -Setup "$work/current.exe" -PreviousSetup "$work/previous.exe" -FixtureDirectory "$work/fixtures" -OutputDirectory "$work/all-users"
Copy-Item -LiteralPath "$work/all-users" -Destination "$evidence/all-users" -Recurse
$account = 'Nuclemu-' + $run
$password = [guid]::NewGuid().ToString('N') + '!aA1'
$secure = ConvertTo-SecureString $password -AsPlainText -Force
New-LocalUser -Name $account -Password $secure -AccountNeverExpires | Out-Null
$users = Get-LocalGroup -SID 'S-1-5-32-545'
Add-LocalGroupMember -Group $users.Name -Member $account
$sid = (Get-LocalUser -Name $account).SID.Value
& icacls.exe $work /inheritance:r | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Cannot protect test workspace inheritance' }
& icacls.exe $work /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' "*$($sid):(OI)(CI)RX" | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Cannot grant read-only test inputs' }
& icacls.exe "$work\*" /reset /T | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Cannot protect administrator test inputs' }
$studentResults = (New-Item -ItemType Directory -Path "$work/student-results").FullName
& icacls.exe $studentResults /grant "*$($sid):(OI)(CI)M" | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Cannot grant standard-account result access' }
$credential = [Management.Automation.PSCredential]::new("$env:COMPUTERNAME\$account",$secure)
$portable = Start-Process 'C:\NuclemuInput\Nuclemu\nuclemu.exe' -ArgumentList 'serve','--no-gui' -WindowStyle Hidden -PassThru -RedirectStandardOutput "$work/portable.out" -RedirectStandardError "$work/portable.err"
$arguments = @('-NoProfile','-ExecutionPolicy','Bypass','-File',"`"$work/scripts/verify-installer.ps1`"",
    '-ExpectedComputerName',$ExpectedComputerName,'-Mode','CurrentUser','-Setup',"$work/current.exe",
    '-PreviousSetup',"$work/previous.exe",'-FixtureDirectory',"$work/fixtures",'-OutputDirectory',"$studentResults/current-user")
$student = Start-Process powershell.exe -Credential $credential -LoadUserProfile -ArgumentList $arguments -WindowStyle Hidden -PassThru -RedirectStandardOutput "$studentResults/student.out" -RedirectStandardError "$studentResults/student.err"
if (!$student.WaitForExit(180000)) { throw 'Standard-user acceptance timed out' }
$student.Refresh()
Copy-Item -LiteralPath "$studentResults/current-user" -Destination "$evidence/current-user" -Recurse -ErrorAction SilentlyContinue
Copy-Item -LiteralPath "$studentResults/student.out","$studentResults/student.err" -Destination $evidence
$resultFile = "$studentResults/current-user/result.json"
if (!(Test-Path -LiteralPath $resultFile) -or
    (Get-Content -LiteralPath $resultFile -Raw | ConvertFrom-Json).result -ne 'PASS' -or
    ($null -ne $student.ExitCode -and $student.ExitCode -ne 0)) {
    throw "Standard-user acceptance failed; see student.err and result.json (exit=$($student.ExitCode))"
}
if ($portable.HasExited) { throw 'Unrelated administrator portable service was closed by a user installation' }
$portable.Kill()
$portable.WaitForExit()
@{result='PASS'; computer=$env:COMPUTERNAME; os=[Environment]::OSVersion.VersionString;
  standard_user=$account; admin_user=$env:USERNAME; networking='Disabled'; utc=[DateTime]::UtcNow.ToString('o')} |
  ConvertTo-Json | Set-Content "$evidence/acceptance.json" -Encoding UTF8
