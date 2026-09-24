#define AppName "QuickEdit"
#define AppVersion "1.0.4"
#define AppPublisher "Blazy Enterprises"
#define AppExeName "QuickEdit.exe"

[Setup]
AppId={{0C2FD654-B44D-4EA4-A81D-C87FD0AA6C6B}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\release
OutputBaseFilename=QuickEdit-1.0.4-Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExeName}
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription=Accessible audio editor and media workbench
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked
Name: "associations"; Description: "Add QuickEdit to Open with for supported audio and MIDI files"; GroupDescription: "File handling:"; Flags: checkedonce
Name: "defaultapps"; Description: "Open Windows Default Apps after installation"; GroupDescription: "File handling:"; Flags: unchecked

[Files]
Source: "..\portable-dist-1.0.4\QuickEdit\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\QuickEdit"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall QuickEdit"; Filename: "{uninstallexe}"
Name: "{autodesktop}\QuickEdit"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExeName}"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "QuickEdit"; Flags: uninsdeletekey; Tasks: associations
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExeName}\shell\open\command"; ValueType: string; ValueData: """{app}\{#AppExeName}"" ""%1"""; Tasks: associations
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExeName}\SupportedTypes"; ValueType: string; ValueName: ".wav"; ValueData: ""; Tasks: associations
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExeName}\SupportedTypes"; ValueType: string; ValueName: ".mp3"; ValueData: ""; Tasks: associations
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExeName}\SupportedTypes"; ValueType: string; ValueName: ".flac"; ValueData: ""; Tasks: associations
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExeName}\SupportedTypes"; ValueType: string; ValueName: ".ogg"; ValueData: ""; Tasks: associations
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExeName}\SupportedTypes"; ValueType: string; ValueName: ".opus"; ValueData: ""; Tasks: associations
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExeName}\SupportedTypes"; ValueType: string; ValueName: ".m4a"; ValueData: ""; Tasks: associations
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExeName}\SupportedTypes"; ValueType: string; ValueName: ".aac"; ValueData: ""; Tasks: associations
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExeName}\SupportedTypes"; ValueType: string; ValueName: ".wma"; ValueData: ""; Tasks: associations
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExeName}\SupportedTypes"; ValueType: string; ValueName: ".aiff"; ValueData: ""; Tasks: associations
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExeName}\SupportedTypes"; ValueType: string; ValueName: ".au"; ValueData: ""; Tasks: associations
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExeName}\SupportedTypes"; ValueType: string; ValueName: ".mid"; ValueData: ""; Tasks: associations
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExeName}\SupportedTypes"; ValueType: string; ValueName: ".midi"; ValueData: ""; Tasks: associations
Root: HKCU; Subkey: "Software\QuickEdit\Capabilities"; ValueType: string; ValueName: "ApplicationName"; ValueData: "QuickEdit"; Flags: uninsdeletekey; Tasks: associations
Root: HKCU; Subkey: "Software\QuickEdit\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "Accessible audio editor and media workbench"; Tasks: associations
Root: HKCU; Subkey: "Software\QuickEdit\Capabilities\FileAssociations"; ValueType: string; ValueName: ".wav"; ValueData: "QuickEdit.Audio"; Tasks: associations
Root: HKCU; Subkey: "Software\QuickEdit\Capabilities\FileAssociations"; ValueType: string; ValueName: ".mp3"; ValueData: "QuickEdit.Audio"; Tasks: associations
Root: HKCU; Subkey: "Software\QuickEdit\Capabilities\FileAssociations"; ValueType: string; ValueName: ".flac"; ValueData: "QuickEdit.Audio"; Tasks: associations
Root: HKCU; Subkey: "Software\QuickEdit\Capabilities\FileAssociations"; ValueType: string; ValueName: ".ogg"; ValueData: "QuickEdit.Audio"; Tasks: associations
Root: HKCU; Subkey: "Software\QuickEdit\Capabilities\FileAssociations"; ValueType: string; ValueName: ".opus"; ValueData: "QuickEdit.Audio"; Tasks: associations
Root: HKCU; Subkey: "Software\QuickEdit\Capabilities\FileAssociations"; ValueType: string; ValueName: ".m4a"; ValueData: "QuickEdit.Audio"; Tasks: associations
Root: HKCU; Subkey: "Software\QuickEdit\Capabilities\FileAssociations"; ValueType: string; ValueName: ".aac"; ValueData: "QuickEdit.Audio"; Tasks: associations
Root: HKCU; Subkey: "Software\QuickEdit\Capabilities\FileAssociations"; ValueType: string; ValueName: ".wma"; ValueData: "QuickEdit.Audio"; Tasks: associations
Root: HKCU; Subkey: "Software\QuickEdit\Capabilities\FileAssociations"; ValueType: string; ValueName: ".aiff"; ValueData: "QuickEdit.Audio"; Tasks: associations
Root: HKCU; Subkey: "Software\QuickEdit\Capabilities\FileAssociations"; ValueType: string; ValueName: ".au"; ValueData: "QuickEdit.Audio"; Tasks: associations
Root: HKCU; Subkey: "Software\QuickEdit\Capabilities\FileAssociations"; ValueType: string; ValueName: ".mid"; ValueData: "QuickEdit.MIDI"; Tasks: associations
Root: HKCU; Subkey: "Software\QuickEdit\Capabilities\FileAssociations"; ValueType: string; ValueName: ".midi"; ValueData: "QuickEdit.MIDI"; Tasks: associations
Root: HKCU; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "QuickEdit"; ValueData: "Software\QuickEdit\Capabilities"; Flags: uninsdeletevalue; Tasks: associations
Root: HKCU; Subkey: "Software\Classes\QuickEdit.Audio"; ValueType: string; ValueData: "Audio file"; Flags: uninsdeletekey; Tasks: associations
Root: HKCU; Subkey: "Software\Classes\QuickEdit.Audio\DefaultIcon"; ValueType: string; ValueData: "{app}\{#AppExeName},0"; Tasks: associations
Root: HKCU; Subkey: "Software\Classes\QuickEdit.Audio\shell\open\command"; ValueType: string; ValueData: """{app}\{#AppExeName}"" ""%1"""; Tasks: associations
Root: HKCU; Subkey: "Software\Classes\QuickEdit.MIDI"; ValueType: string; ValueData: "MIDI file"; Flags: uninsdeletekey; Tasks: associations
Root: HKCU; Subkey: "Software\Classes\QuickEdit.MIDI\DefaultIcon"; ValueType: string; ValueData: "{app}\{#AppExeName},0"; Tasks: associations
Root: HKCU; Subkey: "Software\Classes\QuickEdit.MIDI\shell\open\command"; ValueType: string; ValueData: """{app}\{#AppExeName}"" ""%1"""; Tasks: associations

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch QuickEdit"; Flags: nowait postinstall skipifsilent
Filename: "{sys}\cmd.exe"; Parameters: "/c start """" ms-settings:defaultapps"; Description: "Choose QuickEdit in Windows Default Apps"; Flags: postinstall skipifsilent shellexec; Tasks: defaultapps
