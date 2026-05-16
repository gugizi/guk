# guk

Google Drive의 특정 폴더를 로컬 디렉터리로 자동 백업하는 Python CLI입니다. Drive API를 읽기 전용으로 사용하며, 이전 실행 결과를 manifest에 저장해 변경된 파일만 다시 내려받습니다.

## 기능

- 지정한 Google Drive 폴더를 하위 폴더까지 재귀적으로 백업
- 일반 파일은 원본 그대로 다운로드
- Google Docs/Sheets/Slides/Drawings는 Office 또는 PNG 형식으로 export
- `.gdrive-backup-manifest.json` 기반 증분 백업
- Drive에서 삭제된 파일을 로컬에서도 지우는 선택적 `--prune`
- service account 또는 OAuth Desktop client 인증 지원

## 설치

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

## Google 인증 준비

둘 중 하나를 사용합니다.

### Service account

1. Google Cloud에서 Drive API를 활성화합니다.
2. service account를 만들고 JSON key를 내려받습니다.
3. 백업할 Drive 폴더를 service account 이메일과 공유합니다.
4. 설정 파일의 `auth.service_account_file`에 JSON key 경로를 지정합니다.

### OAuth 사용자 인증

1. Google Cloud에서 Drive API를 활성화합니다.
2. OAuth Desktop client를 만들고 client secrets JSON을 내려받습니다.
3. 설정 파일에서 `service_account_file`을 주석 처리하고 `oauth_client_secrets_file`을 지정합니다.
4. CLI를 한 번 직접 실행해 브라우저 인증을 완료합니다. 이후 refresh token이 저장되어 자동 실행에 사용됩니다.

## 설정

예시는 `examples/backup.example.yaml`에 있습니다.

```yaml
folder_id: "replace-with-drive-folder-id"
destination: "~/backups/google-drive-folder"
include_trashed: false

auth:
  service_account_file: "~/.config/gdrive-folder-backup/service-account.json"
```

Drive 폴더 ID는 폴더 URL의 마지막 값입니다.

```text
https://drive.google.com/drive/folders/<folder_id>
```

## 실행

```bash
gdrive-folder-backup --config examples/backup.example.yaml
```

변경 예정 작업만 확인하려면:

```bash
gdrive-folder-backup --config examples/backup.example.yaml --dry-run
```

Drive에서 사라진 파일을 로컬 백업에서도 제거하려면:

```bash
gdrive-folder-backup --config examples/backup.example.yaml --prune
```

## 자동 백업

cron 또는 systemd timer에서 CLI를 주기적으로 실행하면 됩니다.

cron 예시:

```cron
0 * * * * /path/to/project/.venv/bin/gdrive-folder-backup --config /path/to/backup.yaml >> /var/log/gdrive-folder-backup.log 2>&1
```

systemd user timer를 선호한다면 `ExecStart`에 같은 명령을 넣고 timer의 `OnCalendar`를 원하는 주기로 설정하세요.

## 테스트

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```
