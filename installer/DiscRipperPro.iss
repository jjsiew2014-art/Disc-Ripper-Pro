; Script generated for Disc Ripper Pro
; Professional Inno Setup Script for Disc Ripper Pro v2.0.4

#define MyAppName "Disc Ripper Pro"
#define MyAppVersion "2.0.4"
#define MyAppPublisher "jjsiew2014-art"
#define MyAppURL "https://github.com/jjsiew2014-art/Disc-Ripper-Pro"
#define MyAppExeName "Disc Ripper Pro.exe"
#define MyAppId "{{B4E8B072-88F4-4B2E-99C1-F648D6C81201}"

[Setup]
; Unique application identifier
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} v{#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

; Destination directories
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
LicenseFile=..\LICENSE

; Installer binary properties
OutputDir=..\Release
OutputBaseFilename=Disc Ripper Pro Setup v{#MyAppVersion}
SetupIconFile=..\CompactDisc.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern

; Architecture & Permissions
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog commandline

; Application closure & Upgrade handling
CloseApplications=yes
RestartApplications=no
UsePreviousAppDir=yes

; Uninstall registration
UninstallDisplayIcon={app}\CompactDisc.ico
UninstallDisplayName={#MyAppName} v{#MyAppVersion}
VersionInfoVersion={#MyAppVersion}.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Setup
VersionInfoProductVersion={#MyAppVersion}
DisableWelcomePage=no
DisableDirPage=no
DisableProgramGroupPage=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Main Executable and Core Resources
Source: "..\Release\Disc_Ripper_Pro_Portable_v{#MyAppVersion}\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\Release\Disc_Ripper_Pro_Portable_v{#MyAppVersion}\CompactDisc.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\Release\Disc_Ripper_Pro_Portable_v{#MyAppVersion}\CompactDisc.png"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\Release\Disc_Ripper_Pro_Portable_v{#MyAppVersion}\en.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\Release\Disc_Ripper_Pro_Portable_v{#MyAppVersion}\zh-CN.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\Release\Disc_Ripper_Pro_Portable_v{#MyAppVersion}\zh-TW.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\Release\Disc_Ripper_Pro_Portable_v{#MyAppVersion}\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\Release\Disc_Ripper_Pro_Portable_v{#MyAppVersion}\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\Release\Disc_Ripper_Pro_Portable_v{#MyAppVersion}\launch.bat"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\Release\Disc_Ripper_Pro_Portable_v{#MyAppVersion}\config.json"; DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist skipifsourcedoesntexist

; PyInstaller internal runtime directory
Source: "..\Release\Disc_Ripper_Pro_Portable_v{#MyAppVersion}\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs

; Bundled FFmpeg, FFprobe, and HandBrakeCLI tools
Source: "..\Release\Disc_Ripper_Pro_Portable_v{#MyAppVersion}\ffmpeg\*"; DestDir: "{app}\ffmpeg"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\CompactDisc.ico"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\CompactDisc.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent runasoriginaluser
