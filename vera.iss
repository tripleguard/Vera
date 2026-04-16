; ============================================================
;  Vera — Установщик (Inno Setup 6)
;  Русскоязычный установщик голосового ассистента
; ============================================================

#define MyAppName "Vera"
#define MyAppVersion "1.1.0"
#define MyAppPublisher "TripleGuard"
#define MyAppURL "https://github.com/tripleguard/Vera"
#define MyAppExeName "Vera.exe"

; Путь к staging-каталогу, собранному build.bat
#define StagingDir "build\staging"

[Setup]
AppId={{A7E3F1B2-4C5D-6E7F-8A9B-0C1D2E3F4A5B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
LicenseFile=LICENSE
OutputDir=build\installer
OutputBaseFilename=Vera-Setup-{#MyAppVersion}
SetupIconFile=vera.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64
ArchitecturesAllowed=x64
UninstallDisplayIcon={app}\vera.ico
UninstallDisplayName={#MyAppName}
MinVersion=10.0
DisableProgramGroupPage=yes

; Русский язык
[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

; ============================================================
;  Компоненты установки
; ============================================================
[Types]
Name: "full"; Description: "Полная установка (с LLM и моделью)"
Name: "compact"; Description: "Минимальная установка (внешний LLM)"
Name: "custom"; Description: "Выборочная установка"; Flags: iscustom

[Components]
Name: "main"; Description: "Vera — основное приложение"; Types: full compact custom; Flags: fixed
Name: "llama"; Description: "llama.cpp — локальный LLM-сервер (~75 МБ, из интернета)"; Types: full; ExtraDiskSpaceRequired: 78643200
Name: "model"; Description: "Qwen3.5-2B — языковая модель (Q4_K_M, ~1.2 ГБ, из интернета)"; Types: full; ExtraDiskSpaceRequired: 1288490189

; ============================================================
;  Файлы приложения
; ============================================================
[Files]
; Основное приложение (Electron + Backend)
Source: "{#StagingDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: main

; Скрипты скачивания (всегда включены, для пользователя)
Source: "download_llama_server.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "download_model.py"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
; Папка данных пользователя (всегда в AppData)
Name: "{localappdata}\{#MyAppName}\data"; Permissions: users-modify
Name: "{localappdata}\{#MyAppName}\data\uploads"
Name: "{localappdata}\{#MyAppName}\data\interpreter_tmp"
Name: "{localappdata}\{#MyAppName}\data\plugins"

; ============================================================
;  Ярлыки
; ============================================================
[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\vera.ico"
Name: "{group}\Удалить {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\vera.ico"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\vera.ico"; Tasks: autostart

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Дополнительно:"
Name: "autostart"; Description: "Запускать Vera при входе в Windows"; GroupDescription: "Дополнительно:"; Flags: checkedonce

; ============================================================
;  Действия после установки
; ============================================================
[Run]
; Запуск приложения после установки
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить {#MyAppName}"; Flags: nowait postinstall skipifsilent

; ============================================================
;  Удаление
; ============================================================
[UninstallDelete]
; Удаляем папку приложения, но НЕ данные пользователя в AppData
Type: filesandordirs; Name: "{app}"

; ============================================================
;  Pascal Script — скачивание llama.cpp и модели
; ============================================================
[Code]

var
  DownloadPage: TDownloadWizardPage;

function OnDownloadProgress(const Url, FileName: String; const Progress, ProgressMax: Int64): Boolean;
begin
  if ProgressMax <> 0 then
    Log(Format('  %s: %d / %d байт', [FileName, Progress, ProgressMax]));
  Result := True;
end;

procedure InitializeWizard;
begin
  DownloadPage := CreateDownloadPage(
    'Загрузка компонентов',
    'Пожалуйста, подождите — идёт скачивание дополнительных компонентов...',
    @OnDownloadProgress
  );
  DownloadPage.ShowBaseNameInsteadOfUrl := True;
end;


function NextButtonClick(CurPageID: Integer): Boolean;
var
  ResultCode: Integer;
begin
  Result := True;

  if CurPageID = wpReady then
  begin
    { ── Скачивание модели GGUF ── }
    if IsComponentSelected('model') then
    begin
      DownloadPage.Clear;
      DownloadPage.Add(
        'https://huggingface.co/unsloth/Qwen3.5-2B-GGUF/resolve/main/Qwen3.5-2B-Q4_K_M.gguf?download=true',
        'Qwen3.5-2B-Q4_K_M.gguf',
        ''
      );
      DownloadPage.Show;
      try
        try
          DownloadPage.Download;
        except
          if MsgBox(
            'Не удалось скачать модель автоматически.' + #13#10 +
            'Размер файла: ~1.2 ГБ. Проверьте подключение к интернету.' + #13#10 + #13#10 +
            'Продолжить установку без модели?' + #13#10 +
            'Вы можете скачать её позже вручную с:' + #13#10 +
            'https://huggingface.co/bartowski/Qwen_Qwen3.5-2B-GGUF',
            mbConfirmation, MB_YESNO
          ) = IDNO then
          begin
            Result := False;
            DownloadPage.Hide;
            Exit;
          end;
        end;
      finally
        DownloadPage.Hide;
      end;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  ModelSrc, ModelDst: String;
begin
  if CurStep = ssPostInstall then
  begin
    { ── Копируем скачанную модель в папку приложения ── }
    if IsComponentSelected('model') then
    begin
      ModelSrc := ExpandConstant('{tmp}\Qwen3.5-2B-Q4_K_M.gguf');
      ModelDst := ExpandConstant('{app}\Qwen3.5-2B-Q4_K_M.gguf');
      if FileExists(ModelSrc) then
      begin
        Log('Копирование модели в ' + ModelDst);
        FileCopy(ModelSrc, ModelDst, False);
      end;
    end;

    { ── Скачивание llama-server.exe через PowerShell ── }
    if IsComponentSelected('llama') then
    begin
      Log('Запуск скачивания llama-server.exe...');
      { Скачиваем используя PowerShell + Invoke-RestMethod }
      { Мы принудительно включаем TLS 1.2 и добавляем User-Agent для обхода ограничений GitHub API }
      Exec(
        'powershell.exe',
        '-NoProfile -ExecutionPolicy Bypass -Command "& {' +
          '[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; ' +
          '$headers = @{ ''User-Agent'' = ''VeraInstaller'' }; ' +
          'try { ' +
            '$release = Invoke-RestMethod -Uri ''https://api.github.com/repos/ggml-org/llama.cpp/releases/latest'' -Headers $headers; ' +
            '$asset = $release.assets | Where-Object { $_.name -match ''win.*vulkan.*x64.*\.zip'' } | Select-Object -First 1; ' +
            'if (-not $asset) { ' +
              'Write-Host ''Vulkan version not found, trying CPU version...''; ' +
              '$asset = $release.assets | Where-Object { $_.name -match ''win.*cpu.*x64.*\.zip'' } | Select-Object -First 1; ' +
            '} ' +
            'if ($asset) { ' +
              '$zipPath = Join-Path $env:TEMP ''llama-release.zip''; ' +
              'Write-Host ''Скачивание'' $asset.name ''...''; ' +
              'Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zipPath -UseBasicParsing -Headers $headers; ' +
              'Write-Host ''Распаковка...''; ' +
              '$extractDir = Join-Path $env:TEMP ''llama-extract''; ' +
              'if (Test-Path $extractDir) { Remove-Item $extractDir -Recurse -Force }; ' +
              'Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force; ' +
              'Get-ChildItem -Path $extractDir -Recurse -Include *.exe,*.dll | ForEach-Object { ' +
                'if ($_.Name -ne ''vulkan-1.dll'' -and $_.Name -ne ''vk_swiftshader.dll'') { ' +
                  'Copy-Item $_.FullName -Destination ''' + ExpandConstant('{app}') + ''' -Force ' +
                '} ' +
              '}; ' +
              'Remove-Item $zipPath -Force; ' +
              'Remove-Item $extractDir -Recurse -Force; ' +
              'exit 0; ' +
            '} else { ' +
              'Write-Error ''Не найден подходящий архив llama.cpp''; ' +
              'exit 1; ' +
            '} ' +
          '} catch { ' +
            'Write-Error $_.Exception.Message; ' +
            'exit 1; ' +
          '}' +
        '}"',
        ExpandConstant('{app}'),
        SW_HIDE,
        ewWaitUntilTerminated,
        ResultCode
      );

      if ResultCode <> 0 then
      begin
        MsgBox(
          'Не удалось скачать llama-server.exe автоматически.' + #13#10 +
          'Это может быть связано с ограничением доступа к GitHub API или отсутствием интернета.' + #13#10 + #13#10 +
          'Пожалуйста, выполните установку вручную:' + #13#10 +
          '1. Скачайте архив (vulkan или cpu) с https://github.com/ggml-org/llama.cpp/releases' + #13#10 +
          '2. Извлеките llama-server.exe и все DLL-файлы (кроме vulkan-1.dll) в папку:' + #13#10 +
          '   ' + ExpandConstant('{app}') + #13#10 +
          '3. Если вы выбрали установку модели, поместите скачанный .gguf файл туда же.',
          mbInformation, MB_OK
        );
      end;
    end;
  end;
end;
