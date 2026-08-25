; Установщик AeroPulse для Windows (Inno Setup 6).
;
; Сборка — после PyInstaller, из каталога проекта:
;     pyinstaller aeropulse.spec
;     iscc installer\AeroPulse.iss
;
; Установка «только для меня»: программа кладётся в профиль пользователя, права
; администратора не нужны ни при установке, ни при обновлении. Пользователь у
; программы один, и запрашивать ради него повышение прав не за чем.
;
; Версия не задаётся здесь руками — она читается из свойств собранного exe, куда
; попала из pyproject.toml. Одно место на исходники, exe и установщик: разойтись
; им нельзя, потому что по версии в «Установке и удалении программ» пользователь
; и определяет, что именно у него стоит.

#define AppName "AeroPulse"
#define AppExeName "AeroPulse.exe"
#define DistDir "..\dist\AeroPulse"
#define AppExe DistDir + "\" + AppExeName

#ifnexist AppExe
  #error Не найден dist\AeroPulse\AeroPulse.exe — сначала выполните pyinstaller aeropulse.spec
#endif

#define AppVersion GetStringFileInfo(AppExe, "FileVersion")

[Setup]
; AppId менять нельзя: по нему Windows отличает обновление от второй установки.
AppId={{4349FB0E-CD07-4EC2-9588-A9C8A1D7C7EF}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
VersionInfoVersion={#AppVersion}

; lowest — установка в профиль пользователя, без запроса прав администратора.
; {autopf} при этом раскрывается в {localappdata}\Programs.
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes

; Qt 6.10 работает начиная с Windows 10 1809. Отказ с внятным текстом лучше,
; чем установка, которая молча не запустится.
MinVersion=10.0
ArchitecturesAllowed=x64compatible

OutputDir=..\dist
OutputBaseFilename={#AppName}-Setup-{#AppVersion}
SetupIconFile=..\assets\AeroPulse.ico
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName} {#AppVersion}

WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; \
    Flags: nowait postinstall skipifsilent

; Раздела [UninstallDelete] здесь нет намеренно. База, её копии и журнал лежат в
; %LOCALAPPDATA%\AeroPulse, установщик их туда не клал и при удалении не трогает:
; программу сносят и ставят заново в том числе чтобы починить установку, и
; отчётность за несколько лет такое переживать обязана.
