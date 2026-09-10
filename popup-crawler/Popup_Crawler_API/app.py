import os
import secrets
import json
import subprocess
import threading
import fcntl
from pathlib import Path
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

API_TOKEN = os.environ.get("CRAWLER_API_TOKEN", "").strip()
if not API_TOKEN:
    raise RuntimeError("CRAWLER_API_TOKEN 환경값이 필요합니다.")

PROJECT_DIR = Path("/home/ubuntu/popup-crawler")
RUN_SCRIPT = PROJECT_DIR / "run_daily_server.sh"

STATE_DIR = Path("/home/ubuntu/Popup_Crawler_STATE")
STATUS_FILE = STATE_DIR / "api_crawler_status.json"
LOCK_FILE = STATE_DIR / "api_crawler.lock"

REPORT_FILE = PROJECT_DIR / "data/daily/latest_report.json"

app = FastAPI(
    title="Popup Crawler API",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

bearer = HTTPBearer(auto_error=False)


def require_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
):
    if credentials is None or not secrets.compare_digest(
        credentials.credentials.encode("utf-8"),
        API_TOKEN.encode("utf-8"),
    ):
        raise HTTPException(
            status_code=401,
            detail="인증에 실패했습니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def read_status():
    if not STATUS_FILE.exists():
        return {
            "status": "never_run",
            "message": "아직 API를 통한 실행 기록이 없습니다.",
        }

    try:
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {
            "status": "error",
            "message": "상태 파일을 읽을 수 없습니다.",
        }


def write_status(data):
    data = attach_export_result(data)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    temp_file = STATUS_FILE.with_suffix(".tmp")

    temp_file.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    temp_file.replace(STATUS_FILE)


def process_is_running(pid):
    if not pid:
        return False

    try:
        os.kill(int(pid), 0)
        return True
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        return True


def monitor_process(process_pid, started_at):
    try:
        _, exit_code = os.waitpid(process_pid, 0)

        finished_at = now_iso()

        if exit_code == 0:
            final_status = "success"
        else:
            final_status = "failed"

        write_status(
            {
                "status": final_status,
                "started_at": started_at,
                "finished_at": finished_at,
                "exit_code": exit_code,
                "pid": process_pid,
            }
        )

    except Exception as e:
        write_status(
            {
                "status": "monitor_error",
                "started_at": started_at,
                "finished_at": now_iso(),
                "exit_code": None,
                "pid": process_pid,
                "error": str(e),
            }
        )


def reconcile_running_status(status):
    if status.get("status") != "running":
        return status

    pid = status.get("pid")

    if process_is_running(pid):
        return status

    started_at = status.get("started_at")
    exit_code = None
    final_status = "finished_unknown"

    try:
        if REPORT_FILE.exists() and started_at:
            report_mtime = datetime.fromtimestamp(
                REPORT_FILE.stat().st_mtime,
                tz=timezone.utc,
            )
            started_time = datetime.fromisoformat(started_at)

            if report_mtime > started_time:
                report_data = json.loads(
                    REPORT_FILE.read_text(encoding="utf-8")
                )

                if str(report_data.get("status")).upper() == "SUCCESS":
                    final_status = "success"
                    exit_code = 0
                else:
                    final_status = "failed"
                    exit_code = 1
    except Exception:
        pass

    updated = {
        **status,
        "status": final_status,
        "finished_at": status.get("finished_at") or now_iso(),
        "exit_code": exit_code,
    }

    write_status(updated)
    return updated


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/auth/check", dependencies=[Depends(require_token)])
def auth_check():
    return {"authenticated": True}


@app.post("/api/crawler/run", dependencies=[Depends(require_token)])
def crawler_run():
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    with LOCK_FILE.open("w") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)

        status = reconcile_running_status(read_status())

        if status.get("status") == "running":
            raise HTTPException(
                status_code=409,
                detail="크롤러가 이미 실행 중입니다.",
            )

        if not RUN_SCRIPT.is_file():
            raise HTTPException(
                status_code=500,
                detail="운영 실행 파일을 찾을 수 없습니다.",
            )

        started_at = now_iso()

        try:
            process = subprocess.Popen(
                ["./run_daily_server.sh"],
                cwd=str(PROJECT_DIR),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception as e:
            write_status(
                {
                    "status": "failed",
                    "started_at": started_at,
                    "finished_at": now_iso(),
                    "exit_code": None,
                    "pid": None,
                    "error": str(e),
                }
            )

            raise HTTPException(
                status_code=500,
                detail="크롤러 실행을 시작하지 못했습니다.",
            )

        write_status(
            {
                "status": "running",
                "started_at": started_at,
                "finished_at": None,
                "exit_code": None,
                "pid": process.pid,
            }
        )

        monitor = threading.Thread(
            target=monitor_process,
            args=(process.pid, started_at),
            daemon=True,
        )
        monitor.start()

        return {
            "status": "started",
            "pid": process.pid,
            "started_at": started_at,
        }


@app.get("/api/crawler/status", dependencies=[Depends(require_token)])
def crawler_status():
    return attach_export_result(reconcile_running_status(read_status()))


OUTPUT_DIR = PROJECT_DIR / "output"
BACKEND_OUTPUT_DIR = PROJECT_DIR / "backend_output"


def get_latest_csv():
    files = list(OUTPUT_DIR.glob("*_popup.csv"))
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


@app.get("/api/export/csv", dependencies=[Depends(require_token)])
def export_csv():
    latest_csv = get_latest_csv()

    if latest_csv is None:
        raise HTTPException(
            status_code=404,
            detail="다운로드할 CSV 파일이 없습니다.",
        )

    return FileResponse(
        path=latest_csv,
        media_type="text/csv",
        filename=latest_csv.name,
    )


@app.get("/api/export/json", dependencies=[Depends(require_token)])
def export_json(date: str | None = None):
    if date is None:
        json_file = BACKEND_OUTPUT_DIR / "latest_popup_places.json"
    else:
        if len(date) != 8 or any(c not in "0123456789" for c in date):
            raise HTTPException(
                status_code=400,
                detail="날짜는 YYYYMMDD 형식으로 입력해 주세요.",
            )
        try:
            datetime.strptime(date, "%Y%m%d")
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="올바른 날짜를 입력해 주세요.",
            )

        json_file = BACKEND_OUTPUT_DIR / f"{date}_popup_places.json"

    if not json_file.is_file():
        raise HTTPException(
            status_code=404,
            detail="요청한 JSON 파일이 없습니다.",
        )

    return FileResponse(
        path=json_file,
        media_type="application/json",
        filename=json_file.name,
    )


def attach_export_result(status):
    if status.get("status") != "success" or "result" in status:
        return status
    result = None
    try:
        started = datetime.fromisoformat(status["started_at"]).timestamp()
        finished = datetime.fromisoformat(status["finished_at"]).timestamp()
        report_path = BACKEND_OUTPUT_DIR / "latest_export_report.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        generated = datetime.fromisoformat(report["generated_at"]).timestamp()
        output = Path(report["output_json"]).resolve()
        date = output.name.removesuffix("_popup_places.json")
        if (
            len(date) != 8
            or any(c not in "0123456789" for c in date)
            or output.name != f"{date}_popup_places.json"
        ):
            raise ValueError("Unexpected filename")
        datetime.strptime(date, "%Y%m%d")
        if (
            output.parent == BACKEND_OUTPUT_DIR.resolve()
            and output.is_file()
            and int(started) <= generated <= finished
            and started <= report_path.stat().st_mtime <= finished
            and started <= output.stat().st_mtime <= finished
        ):
            result = {
                "filename": output.name,
                "date": date,
                "count": report.get("count"),
                "download_path": f"/api/export/json?date={date}",
            }
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return {**status, "result": result}
