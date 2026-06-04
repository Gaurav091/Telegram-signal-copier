#define MyAppName "Telegram Signal Copier"
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#define MyAppExeName "TelegramSignalCopier.exe"

[Setup]
AppId={{B91ED964-6A10-4C42-9D85-D322AC0F61B8}
AppName={#MyAppName}
AppVersion={#AppVersion}
AppPublisher=Telegram Signal Copier
DefaultDirName={autopf}\Telegram Signal Copier
DefaultGroupName={#MyAppName}
OutputDir=..\dist\installer
OutputBaseFilename=TelegramSignalCopier-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
PrivilegesRequired=admin
UninstallDisplayIcon={app}\{#MyAppExeName}

[Files]
Source: "..\dist\TelegramSignalCopier\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\.env.example"; DestDir: "{userappdata}\TelegramSignalCopier"; DestName: ".env.example"; Flags: onlyifdoesntexist

[Icons]
Name: "{group}\Setup Wizard"; Filename: "{app}\{#MyAppExeName}"; Parameters: "setup"; WorkingDir: "{userappdata}\TelegramSignalCopier"; Comment: "First-run configuration wizard"
Name: "{group}\Start Listener"; Filename: "{app}\{#MyAppExeName}"; Parameters: "listen"; WorkingDir: "{userappdata}\TelegramSignalCopier"
Name: "{group}\Telegram Login"; Filename: "{app}\{#MyAppExeName}"; Parameters: "login"; WorkingDir: "{userappdata}\TelegramSignalCopier"
Name: "{group}\Open Config Folder"; Filename: "{win}\explorer.exe"; Parameters: """{userappdata}\TelegramSignalCopier"""
Name: "{group}\README"; Filename: "{app}\README.md"

[Run]
Filename: "{app}\{#MyAppExeName}"; Parameters: "setup"; WorkingDir: "{userappdata}\TelegramSignalCopier"; Description: "Run Setup Wizard now"; Flags: postinstall nowait skipifsilent