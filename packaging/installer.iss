; Inno Setup script for AI Job Finder (section 36/39: a `.exe` a
; non-technical user can install and use).
;
; Prerequisite: build the frozen app first -
;   pyinstaller --noconfirm packaging\aijobfinder.spec
; which produces dist\AIJobFinder\AIJobFinder.exe plus its _internal/
; support files. This script packages that folder into a single
; AIJobFinder-Setup.exe installer.
;
; Build with (Inno Setup 6, https://jrsoftware.org/isinfo.php):
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\installer.iss
; Output: packaging\dist_installer\AIJobFinder-Setup.exe
;
; What this installer does - and does not - do:
;   - Copies the already-built dist\AIJobFinder folder to
;     {autopf}\AI Job Finder (Program Files, per-machine by default; the
;     user can switch to a per-user install at the license/dir prompt).
;   - Creates Start Menu and optional Desktop shortcuts.
;   - Offers to launch the app after install.
;   - Does NOT touch user data: the database, logs, and uploaded resumes
;     always live in %LOCALAPPDATA%\AIJobFinder (see app/core/paths.py),
;     never inside the install folder, so uninstalling never deletes a
;     user's resumes/history, and reinstalling/upgrading never resets them.
;   - Uninstalling removes only the installed program files, never the
;     data directory above - a deliberate choice so "reinstall to fix
;     something" is always safe.

#define MyAppName "AI Job Finder"
#define MyAppVersion "0.3.1"
#define MyAppPublisher "AI Job Finder"
#define MyAppExeName "AIJobFinder.exe"
#define MyBuiltDir "..\dist\AIJobFinder"

[Setup]
AppId={{B6E2B7B0-9C3A-4C2F-9E9B-AAA1C0F5E001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\AI Job Finder
DefaultGroupName=AI Job Finder
DisableProgramGroupPage=yes
SetupIconFile=app_icon.ico
Compression=lzma2
SolidCompression=yes
OutputDir=dist_installer
OutputBaseFilename=AIJobFinder-Setup
WizardStyle=modern
; The ML dependency stack makes the install large - inform the user via
; a normal progress UI rather than the terse minimal wizard.
DisableWelcomePage=no
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
; Recursively packages everything PyInstaller produced (the .exe plus its
; _internal folder of DLLs/data files) - never hand-pick individual files
; here, since the ML dependency set changes what's needed over time.
Source: "{#MyBuiltDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\AI Job Finder"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall AI Job Finder"; Filename: "{uninstallexe}"
Name: "{autodesktop}\AI Job Finder"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch AI Job Finder now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Deliberately empty: user data lives outside {app} (see header comment)
; and must survive an uninstall. Nothing extra to clean up here.
