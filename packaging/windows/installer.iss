; Compile the existing offline application directory. No downloads at install time.
#ifndef PayloadDir
  #define PayloadDir "..\..\dist\Nuclemu"
#endif
#ifndef ReleaseDir
  #define ReleaseDir "..\..\dist\release"
#endif
#ifndef AppVersion
  #define AppVersion "0.0.1"
#endif
#ifndef OutputName
  #define OutputName "Nuclemu-" + AppVersion + "-windows-x64-setup"
#endif
#ifndef PayloadManifest
  #error Build with build-installer.ps1 to generate the managed-file ledger.
#endif

[Setup]
AppId={{EDDB3BC4-699D-4824-BF85-4FE3A3B2A326}
AppName=Nuclemu
AppVersion={#AppVersion}
AppPublisher=Nuclemu contributors
AppPublisherURL=https://github.com/msjs2333/Nuclemu
AppSupportURL=https://github.com/msjs2333/Nuclemu/issues
AppUpdatesURL=https://github.com/msjs2333/Nuclemu/releases
DefaultDirName={autopf}\Nuclemu
DefaultGroupName=Nuclemu
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UsePreviousPrivileges=yes
UsePreviousAppDir=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; CPython 3.12 / managed Windows distribution requires Windows 8.1 (Inno 6.3).
; This is an upstream runtime gate, not a claim of testing on Windows 8.1.
MinVersion=6.3
OutputDir={#ReleaseDir}
OutputBaseFilename={#OutputName}
SetupIconFile={#PayloadDir}\_internal\nuclemu\static\nuclemu.ico
UninstallDisplayIcon={app}\Nuclemu-Desktop.exe
LicenseFile={#PayloadDir}\_internal\licenses\Nuclemu\LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=no
RestartApplications=no
SetupLogging=yes
UninstallDisplayName=Nuclemu

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "chinesesimp"; MessagesFile: "ChineseSimplified.isl"

[Files]
Source: "{#PayloadManifest}"; DestDir: "{app}"; DestName: ".nuclemu-installed-files"; Flags: ignoreversion
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "Inno-Setup-LICENSE.txt"; DestDir: "{app}\licenses\Inno Setup"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Nuclemu"; Filename: "{app}\Nuclemu-Desktop.exe"; WorkingDir: "{app}"

[Run]
Filename: "{app}\Nuclemu-Desktop.exe"; Description: "{cm:LaunchProgram,Nuclemu}"; Flags: nowait postinstall skipifsilent runasoriginaluser

[CustomMessages]
english.RunningApp=Please save your experiment and close Nuclemu before updating or uninstalling it.
chinesesimp.RunningApp=请先保存实验并关闭 Nuclemu，再更新或卸载。
english.CheckFailed=Unable to check whether Nuclemu is running. Please try again after restoring Windows Management Instrumentation.
chinesesimp.CheckFailed=无法检查 Nuclemu 是否正在运行。请恢复 Windows 管理规范服务后重试。

[Code]
var
  PreviousFiles: TArrayOfString;

function ApplicationBlockReason(): String;
var
  Locator, Services, Processes, Process: Variant;
  Index: Integer;
  InstalledDir, Executable: String;
begin
  Result := '';
  InstalledDir := ExpandConstant('{app}');
  if not DirExists(InstalledDir) then exit;
  try
  Locator := CreateOleObject('WbemScripting.SWbemLocator');
  Services := Locator.ConnectServer('', 'root\CIMV2');
  Processes := Services.ExecQuery('SELECT ExecutablePath FROM Win32_Process WHERE ' +
    'Name="Nuclemu-Desktop.exe" OR Name="nuclemu.exe"');
  for Index := 0 to Processes.Count - 1 do begin
    Process := Processes.ItemIndex(Index);
    { Other users' unrelated portable copies can have inaccessible paths. }
    if not VarIsNull(Process.ExecutablePath) then begin
      Executable := Process.ExecutablePath;
      if CompareText(ExtractFileDir(Executable), InstalledDir) = 0 then begin
        Result := CustomMessage('RunningApp');
        exit;
      end;
    end;
  end;
  except
    Result := CustomMessage('CheckFailed') + #13#10 + GetExceptionMessage;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  CurrentFiles: TStringList;
  Index: Integer;
  Relative, Target, Root: String;
begin
  if CurStep = ssInstall then
    LoadStringsFromFile(ExpandConstant('{app}\.nuclemu-installed-files'), PreviousFiles);
  if CurStep = ssPostInstall then begin
    CurrentFiles := TStringList.Create;
    try
      CurrentFiles.LoadFromFile(ExpandConstant('{app}\.nuclemu-installed-files'));
      Root := AddBackslash(ExpandConstant('{app}'));
      for Index := 0 to GetArrayLength(PreviousFiles) - 1 do begin
        Relative := PreviousFiles[Index];
        { Only remove recorded payload files, never arbitrary app/user folders. }
        if (Relative <> '') and (Pos('..', Relative) = 0) and
           (Pos(':', Relative) = 0) and (Relative[1] <> '\') and (Relative[1] <> '/') and
           (CurrentFiles.IndexOf(Relative) < 0) then begin
          Target := ExpandFileName(Root + Relative);
          if (CompareText(Copy(Target, 1, Length(Root)), Root) = 0) and FileExists(Target) then begin
            if not DeleteFile(Target) then
              RaiseException('Unable to remove obsolete Nuclemu program file: ' + Relative);
            Log('Removed obsolete payload: ' + Relative);
          end;
        end;
      end;
    finally
      CurrentFiles.Free;
    end;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := ApplicationBlockReason();
end;

function InitializeUninstall(): Boolean;
var
  Reason: String;
begin
  Reason := ApplicationBlockReason();
  Result := Reason = '';
  if not Result then
    SuppressibleMsgBox(Reason, mbInformation, MB_OK, IDOK);
end;

// User preferences, workbench databases and saved experiments are outside {app}.
// Deliberately no UninstallDelete or removal of user profile folders.
