# Popup Crawler API

Ubuntu에서 Popup Crawler V1.2를 실행하고 상태와 결과 파일을 제공하는 FastAPI 서비스입니다.

## API

- `GET /health`: 서비스 상태 확인
- `GET /api/auth/check`: Bearer 토큰 확인
- `POST /api/crawler/run`: `run_daily_server.sh` 백그라운드 실행
- `GET /api/crawler/status`: 실행 상태와 성공한 결과 파일 정보 확인
- `GET /api/export/json`: 최신 JSON 다운로드
- `GET /api/export/json?date=YYYYMMDD`: 날짜별 JSON 다운로드
- `GET /api/export/csv`: 최신 CSV 다운로드

성공한 상태 응답에는 실제 생성된 파일 정보가 포함됩니다.

```json
{
  "status": "success",
  "result": {
    "filename": "20260910_popup_places.json",
    "date": "20260910",
    "count": 446,
    "download_path": "/api/export/json?date=20260910"
  }
}
```

`result`는 해당 실행 시간 안에 생성된 보고서와 JSON이 확인된 경우에만 추가됩니다. 이전 실행 결과가 현재 실행에 연결되는 것을 막기 위한 조건입니다.

## 서버 배치

1. 이 폴더를 `/home/ubuntu/popup-crawler-api`에 배치합니다.
2. `.env.example`을 `.env`로 복사하고 긴 임의 토큰을 설정합니다.
3. 크롤러 가상환경에 `requirements.txt`를 설치합니다.
4. `popup-crawler-api.service`를 `/etc/systemd/system`에 설치하고 활성화합니다.

`.env`와 실제 토큰은 Git에 올리지 않습니다. 외부 공개 시에는 HTTPS 프록시 뒤에서 사용합니다.

## n8n 연결

매일 오전 8시 실행 요청 후 상태가 `running`인 동안 대기와 조회를 반복합니다. `success`이면 아래 식으로 실제 결과 파일을 다운로드합니다.

```javascript
{{ 'https://crawler.example.com' + $json.result.download_path }}
```

실패 분기는 `Stop And Error`로 종료하고, 별도의 Error Trigger 워크플로에서 SMTP 이메일을 발송합니다.

`download_popup.py`는 한국 시간 기준 오늘 날짜의 JSON을 내려받습니다. 배포 환경에서 `CRAWLER_API_URL`과 `CRAWLER_API_TOKEN` 환경변수를 지정하거나, 비공개 전달본에서 토큰 상수를 채운 뒤 실행합니다.
