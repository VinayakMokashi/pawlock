; PawLock installer for Windows (Inno Setup 6).
;
; Build:   python scripts/build.py --installer
;   or:    ISCC /DMyAppVersion=1.2.0 packaging\windows\PawLock.iss   (after building dist\PawLock.exe)
;
; What it does, in plain words:
;   * installs PawLock for the current user only: no administrator password needed
;     (%LOCALAPPDATA%\Programs\PawLock)
;   * adds "PawLock" and an emergency "Stop PawLock" to the Start menu
;   * optionally starts PawLock when you sign in (on by default) and adds a desktop icon
;   * stops a running PawLock before upgrading or uninstalling
;   * shows up in Settings > Apps, where it can be uninstalled like any other app

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppName "PawLock"
#define MyAppExe "PawLock.exe"
#define MyAppUrl "https://github.com/VinayakMokashi/pawlock"

[Setup]
AppId={{6F4B2C1E-8A3D-4F5B-9C7E-2D1A0B9C8E7F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=PawLock
AppPublisherURL={#MyAppUrl}
AppSupportURL={#MyAppUrl}/blob/main/docs/TROUBLESHOOTING.md
AppUpdatesURL={#MyAppUrl}/releases
VersionInfoVersion={#MyAppVersion}
VersionInfoDescription=PawLock setup
; Per-user install: no admin prompt. {autopf} becomes %LOCALAPPDATA%\Programs.
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#MyAppName}
; Short wizard: Welcome -> Options -> Finish. No folder or "ready" questions.
DisableWelcomePage=no
DisableProgramGroupPage=yes
DisableDirPage=yes
DisableReadyPage=yes
OutputDir=..\..\dist
OutputBaseFilename=PawLock-Setup-{#MyAppVersion}
SetupIconFile=..\..\assets\pawlock.ico
UninstallDisplayIcon={app}\{#MyAppExe}
UninstallDisplayName={#MyAppName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; We stop PawLock ourselves (below); no "close applications" page needed.
CloseApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
WelcomeLabel2=This will install [name/ver] on your computer.%n%nPawLock locks your keyboard and trackpad when a cat walks, sits or sleeps on them, and locks by itself when you leave the room.%n%nUnlock any time with Ctrl + Alt + Shift + L.
FinishedLabel=PawLock is installed. Look for the paw icon next to the clock.%n%nTo lock or unlock: press Ctrl + Alt + Shift + L (or type the word "unlock" while locked).

[Tasks]
Name: "autostart"; Description: "Start PawLock automatically when I sign in (recommended)"; GroupDescription: "Options:"
Name: "desktopicon"; Description: "Put a PawLock icon on the desktop"; GroupDescription: "Options:"; Flags: unchecked

[Files]
Source: "..\..\dist\{#MyAppExe}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\PawLock"; Filename: "{app}\{#MyAppExe}"; Comment: "Cat-proof your keyboard and trackpad"
Name: "{autoprograms}\Stop PawLock"; Filename: "{app}\{#MyAppExe}"; Parameters: "--stop"; Comment: "Emergency stop: gives you back your keyboard and mouse"
Name: "{autodesktop}\PawLock"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Registry]
; Same entry PawLock's own "Start at login" option uses, so the two stay in sync.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "PawLock"; ValueData: """{app}\{#MyAppExe}"""; Tasks: autostart; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Start PawLock now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\{#MyAppExe}"; Parameters: "--stop --quiet"; Flags: runhidden waituntilterminated; RunOnceId: "StopPawLock"

[Code]
procedure StopRunningPawLock();
var
  ResultCode: Integer;
begin
  { A running PawLock locks its .exe; ask it to stop (no dialogs) before replacing it. }
  if FileExists(ExpandConstant('{app}\{#MyAppExe}')) then
    Exec(ExpandConstant('{app}\{#MyAppExe}'), '--stop --quiet', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopRunningPawLock();
  Result := '';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  { Remove "start at login" even if it was switched on later from inside PawLock. }
  if CurUninstallStep = usPostUninstall then
    RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', 'PawLock');
end;
