; Inno Setup script for Mouser (Windows installer)
; Builds a per-user installer that adds Mouser to the Start Menu.
;
; Prerequisites:
;   1. Build the app first:  pyinstaller Mouser.spec --noconfirm
;      (produces dist\Mouser\Mouser.exe)
;   2. Compile this script:  ISCC packaging\windows\Mouser.iss
;      Output: dist\installer\Mouser-Setup-<version>.exe

#define MyAppName "Mouser"
#ifndef MyAppVersion
  #define MyAppVersion "3.7.3"
#endif
#define MyAppPublisher "TomBadash"
#define MyAppURL "https://github.com/TomBadash/Mouser"
#define MyAppExeName "Mouser.exe"

; Path to the PyInstaller COLLECT output, relative to this script.
#ifndef SourceDir
  #define SourceDir "..\..\dist\Mouser"
#endif

[Setup]
; A stable, unique AppId so upgrades replace the prior install.
AppId={{8F4B2E71-9C3A-4D5E-B6F1-2A7C9D0E3F45}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Per-user install: no administrator prompt, lands in the user's
; Start Menu and %LOCALAPPDATA%\Programs. The user can still elevate
; to an all-users install from the wizard if they choose.
PrivilegesRequired=lowest
OutputDir=..\..\dist\installer
OutputBaseFilename=Mouser-Setup-{#MyAppVersion}
SetupIconFile=..\..\images\logo.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
