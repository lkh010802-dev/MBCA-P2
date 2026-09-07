from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend_adapter.popup_backend_adapter import export_backend_json


SEOUL_TZ = ZoneInfo("Asia/Seoul")
ROOT = Path(__file__).resolve().parent
VERSION = "1.0.1"


@dataclass
class StageResult:
    name: str
    command: list[str]
    returncode: int
    duration_seconds: float
    output: str
    run_dir: str | None = None


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def list_run_dirs(base: Path) -> set[Path]:
    if not base.exists():
        return set()
    return {p.resolve() for p in base.iterdir() if p.is_dir()}


def newest_run_dir(base: Path) -> Path | None:
    if not base.exists():
        return None
    candidates = [p for p in base.iterdir() if p.is_dir()]
    return max(candidates, key=lambda p: p.stat().st_mtime, default=None)


def newest_report(base: Path) -> tuple[Path | None, dict[str, Any] | None]:
    run_dir = newest_run_dir(base)
    if not run_dir:
        return None, None
    report_path = run_dir / "report.json"
    if not report_path.exists():
        report_path = run_dir / "run_report.json"
    if not report_path.exists():
        return run_dir, None
    try:
        return run_dir, read_json(report_path)
    except (OSError, json.JSONDecodeError):
        return run_dir, None


def _display_command(command: list[str]) -> str:
    return " ".join(f'"{x}"' if " " in x else x for x in command)


def run_stage(
    name: str,
    command: list[str],
    run_base: Path,
    *,
    output_prefix: str = "",
) -> StageResult:
    before = list_run_dirs(run_base)
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUNBUFFERED", "1")

    print()
    print(f"===== {name} =====")
    print(f"> {_display_command(command)}")
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    captured: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        print(f"{output_prefix}{line}", end="", flush=True)
        captured.append(line)
    returncode = process.wait()
    duration = round(time.monotonic() - started, 2)
    print(f"{output_prefix}[{name} 완료] {duration:.1f}s", flush=True)

    after = list_run_dirs(run_base)
    new_dirs = list(after - before)
    run_dir = max(new_dirs, key=lambda p: p.stat().st_mtime, default=None)
    if run_dir is None:
        run_dir = newest_run_dir(run_base)

    return StageResult(
        name=name,
        command=command,
        returncode=returncode,
        duration_seconds=duration,
        output="".join(captured),
        run_dir=str(run_dir) if run_dir else None,
    )


def source_count_from_report(source: str, report: dict[str, Any] | None) -> int | None:
    if not report:
        return None
    if source == "dayforyou":
        value = report.get("seoul_total")
    else:
        value = report.get("candidate_count")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def retention_warning(
    source: str,
    new_count: int,
    previous_count: int | None,
    *,
    min_retention: float,
    min_source_count: int,
) -> str | None:
    if new_count < min_source_count:
        return f"{source}: candidate_count={new_count} < minimum={min_source_count}"
    if previous_count and previous_count > 0:
        ratio = new_count / previous_count
        if ratio < min_retention:
            return (
                f"{source}: count dropped to {ratio:.1%} of previous run "
                f"({previous_count} -> {new_count}), below {min_retention:.0%} gate"
            )
    return None


def validate_dayforyou(
    run_dir: Path,
    report: dict[str, Any],
    *,
    previous_count: int | None,
    min_retention: float,
    min_source_count: int,
    max_detail_failure_rate: float,
) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    count = source_count_from_report("dayforyou", report) or 0
    retention = retention_warning(
        "dayforyou", count, previous_count,
        min_retention=min_retention, min_source_count=min_source_count,
    )
    if retention:
        errors.append(retention)

    final_path = run_dir / "final_popup_db.jsonl"
    if not final_path.exists():
        errors.append("dayforyou: final_popup_db.jsonl missing (LLM/manual stage may be incomplete)")

    detail_total = int(report.get("detail_success") or 0) + int(report.get("detail_failed") or 0)
    detail_failed = int(report.get("detail_failed") or 0)
    failure_rate = detail_failed / detail_total if detail_total else 0.0
    if failure_rate > max_detail_failure_rate:
        errors.append(
            f"dayforyou: detail failure rate {failure_rate:.1%} exceeds {max_detail_failure_rate:.1%}"
        )
    elif detail_failed:
        warnings.append(f"dayforyou: detail failures {detail_failed}/{detail_total}")

    hours_found = int(report.get("operation_hours_found") or 0)
    hours_missing = int(report.get("operation_hours_missing") or 0)
    hours_total = hours_found + hours_missing
    hours_rate = hours_found / hours_total if hours_total else 0.0
    if hours_total and hours_rate < 0.80:
        warnings.append(
            f"dayforyou: operating-hours coverage {hours_rate:.1%} "
            f"({hours_found}/{hours_total}); inspect operation_hours_missing_details.jsonl"
        )

    llm_candidates = int(report.get("llm_candidate_count") or 0)
    llm_executed = bool(report.get("llm_executed"))
    llm_report = report.get("llm_report") or {}
    manual_review = int(llm_report.get("manual_review") or 0)
    llm_calls = int(llm_report.get("api_calls") or 0)
    if llm_candidates and not llm_executed:
        errors.append(f"dayforyou: {llm_candidates} LLM candidates remain but LLM was not executed")
    if manual_review:
        errors.append(f"dayforyou: {manual_review} LLM/manual review records remain")

    metrics = {
        "candidate_count": count,
        "previous_candidate_count": previous_count,
        "detail_failed": detail_failed,
        "detail_failure_rate": round(failure_rate, 4),
        "operation_hours_found": hours_found,
        "operation_hours_missing": hours_missing,
        "operation_hours_coverage": round(hours_rate, 4),
        "llm_candidate_count": llm_candidates,
        "llm_executed": llm_executed,
        "llm_calls": llm_calls,
        "manual_review": manual_review,
        "output": str(final_path),
    }
    return errors, warnings, metrics


def validate_popga(
    run_dir: Path,
    report: dict[str, Any],
    *,
    previous_count: int | None,
    min_retention: float,
    min_source_count: int,
    max_detail_failure_rate: float,
) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    count = source_count_from_report("popga", report) or 0
    retention = retention_warning(
        "popga", count, previous_count,
        min_retention=min_retention, min_source_count=min_source_count,
    )
    if retention:
        errors.append(retention)

    output = run_dir / "normalized_with_details.jsonl"
    if not output.exists():
        errors.append("popga: normalized_with_details.jsonl missing")

    detail = report.get("detail_fetch") or {}
    requested = int(detail.get("requested_count") or 0)
    failed = int(detail.get("failed_count") or 0)
    if not detail:
        errors.append("popga: full detail stage was not executed")
    if requested != count:
        errors.append(f"popga: detail requested_count={requested} != candidate_count={count}")
    failure_rate = failed / requested if requested else 0.0
    if failure_rate > max_detail_failure_rate:
        errors.append(f"popga: detail failure rate {failure_rate:.1%} exceeds {max_detail_failure_rate:.1%}")
    elif failed:
        warnings.append(f"popga: detail failures {failed}/{requested}")

    metrics = {
        "candidate_count": count,
        "previous_candidate_count": previous_count,
        "detail_requested": requested,
        "detail_failed": failed,
        "detail_failure_rate": round(failure_rate, 4),
        "detail_cache_hits": int(detail.get("cache_hit_count") or 0),
        "detail_live_fetches": int(detail.get("live_fetch_count") or 0),
        "output": str(output),
    }
    return errors, warnings, metrics


def validate_popply(
    run_dir: Path,
    report: dict[str, Any],
    *,
    previous_count: int | None,
    min_retention: float,
    min_source_count: int,
    max_detail_failure_rate: float,
    max_core_incomplete_count: int = 2,
    max_core_incomplete_rate: float = 0.02,
) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    count = source_count_from_report("popply", report) or 0
    retention = retention_warning(
        "popply", count, previous_count,
        min_retention=min_retention, min_source_count=min_source_count,
    )
    if retention:
        errors.append(retention)

    audit_output = run_dir / "normalized_with_details.jsonl"
    output = run_dir / "normalized_for_integration.jsonl"
    if not audit_output.exists():
        errors.append("popply: normalized_with_details.jsonl missing")
    if not output.exists():
        # Backward compatibility for pre-v0.9.7 runs.
        output = audit_output

    detail = report.get("detail_fetch") or {}
    requested = int(detail.get("requested_count") or 0)
    failed = int(detail.get("failed_count") or 0)
    if not detail:
        errors.append("popply: full detail stage was not executed")
    if bool(detail.get("is_partial")):
        errors.append("popply: partial detail result cannot be used for daily commit")
    if requested != count:
        errors.append(f"popply: detail requested_count={requested} != candidate_count={count}")
    failure_rate = failed / requested if requested else 0.0
    if failure_rate > max_detail_failure_rate:
        errors.append(f"popply: detail failure rate {failure_rate:.1%} exceeds {max_detail_failure_rate:.1%}")
    elif failed:
        warnings.append(f"popply: detail failures {failed}/{requested}")

    core_incomplete = int(detail.get("core_detail_incomplete_count") or 0)
    core_incomplete_rate = core_incomplete / requested if requested else 0.0
    quarantine_count = int(detail.get("quarantine_count") or core_incomplete or failed)
    integration_usable = int(detail.get("integration_usable_count") or max(0, count - quarantine_count))
    quarantine_names = [str(x) for x in (detail.get("quarantine_names") or [])]

    # 한두 건의 단발성 hydration 실패 때문에 하루 전체를 버리지는 않는다.
    # 작은 실패는 quarantine에서 제외한 뒤 통합을 계속하고, 규모가 커질 때만 block한다.
    if core_incomplete and (
        core_incomplete > max_core_incomplete_count
        or core_incomplete_rate > max_core_incomplete_rate
    ):
        errors.append(
            f"popply: core detail incomplete {core_incomplete}/{requested} "
            f"({core_incomplete_rate:.1%}) exceeds quarantine allowance; master commit blocked"
        )
    elif core_incomplete:
        preview = ", ".join(quarantine_names[:3]) if quarantine_names else "source_id in detail_quarantine.jsonl"
        warnings.append(
            f"popply: quarantined {core_incomplete}/{requested} incomplete detail record(s); "
            f"integration continues without them ({preview})"
        )

    crawl_diag = report.get("crawl_diagnostics") or {}
    status_refresh_suspect = int(crawl_diag.get("status_refresh_suspect_count") or 0)
    if status_refresh_suspect:
        errors.append(
            "popply: status filter card refresh remained suspicious after retry; "
            f"statuses={crawl_diag.get('status_refresh_suspect_statuses') or []}"
        )

    metrics = {
        "candidate_count": count,
        "previous_candidate_count": previous_count,
        "detail_requested": requested,
        "detail_failed": failed,
        "detail_failure_rate": round(failure_rate, 4),
        "detail_cache_hits": int(detail.get("cache_hit_count") or 0),
        "detail_live_fetches": int(detail.get("live_fetch_count") or 0),
        "detail_cache_recoveries": int(detail.get("cache_recovery_count") or 0),
        "detail_core_incomplete": core_incomplete,
        "detail_core_incomplete_rate": round(core_incomplete_rate, 4),
        "integration_usable_count": integration_usable,
        "quarantine_count": quarantine_count,
        "quarantine_names": quarantine_names,
        "quarantine_file": str(run_dir / "detail_quarantine.jsonl"),
        "detail_live_retried": int(detail.get("retried_live_count") or 0),
        "status_filter_retries": crawl_diag.get("status_retry_counts") or {},
        "status_overlap_ratios": crawl_diag.get("status_overlap_ratios") or {},
        "status_refresh_suspect": status_refresh_suspect,
        "output": str(output),
    }
    return errors, warnings, metrics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="v1.0.0 one-command daily crawler + integration + quarantine + daily changes + backend CSV"
    )
    parser.add_argument(
        "--reuse-latest",
        action="store_true",
        help="새 크롤링 없이 각 source의 최신 정상 출력으로 daily integration만 검증",
    )
    parser.add_argument(
        "--no-commit",
        action="store_true",
        help="master를 갱신하지 않고 integration candidate만 생성",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="DayForYou LLM fallback을 호출하지 않음. 후보가 남으면 master commit은 중단됨",
    )
    parser.add_argument(
        "--min-source-retention",
        type=float,
        default=float(os.getenv("DAILY_MIN_SOURCE_RETENTION", "0.65")),
        help="이전 실행 대비 source 건수 최소 비율. 기본 0.65",
    )
    parser.add_argument(
        "--min-source-count",
        type=int,
        default=int(os.getenv("DAILY_MIN_SOURCE_COUNT", "10")),
        help="source별 최소 후보 수. 기본 10",
    )
    parser.add_argument(
        "--max-detail-failure-rate",
        type=float,
        default=float(os.getenv("DAILY_MAX_DETAIL_FAILURE_RATE", "0.05")),
        help="상세 수집 허용 실패율. 기본 0.05",
    )
    parser.add_argument(
        "--max-popply-core-incomplete-count",
        type=int,
        default=int(os.getenv("DAILY_MAX_POPPLY_CORE_INCOMPLETE_COUNT", "2")),
        help="Popply 상세 핵심필드 불완전 quarantine 허용 건수. 기본 2",
    )
    parser.add_argument(
        "--max-popply-core-incomplete-rate",
        type=float,
        default=float(os.getenv("DAILY_MAX_POPPLY_CORE_INCOMPLETE_RATE", "0.02")),
        help="Popply 상세 핵심필드 불완전 quarantine 허용 비율. 기본 0.02",
    )
    parser.add_argument(
        "--sequential-sources",
        action="store_true",
        help="Popga/Popply를 동시에 돌리지 않고 순차 실행(저사양 PC용)",
    )
    return parser.parse_args()


def _load_source_run(source: str, run_dir: Path) -> tuple[dict[str, Any], Path]:
    report_path = run_dir / "report.json"
    if not report_path.exists():
        raise FileNotFoundError(f"{source}: report.json missing: {run_dir}")
    report = read_json(report_path)
    if source == "dayforyou":
        output = run_dir / "final_popup_db.jsonl"
    else:
        output = run_dir / "normalized_with_details.jsonl"
    return report, output


def _summary_text(report: dict[str, Any]) -> str:
    sources = report.get("sources") or {}
    lines = [
        f"Popup Crawler Daily v{VERSION}",
        f"status: {report.get('status')}",
        f"started_at: {report.get('started_at')}",
        f"finished_at: {report.get('finished_at')}",
        "",
    ]
    for source in ("dayforyou", "popga", "popply"):
        item = sources.get(source) or {}
        metrics = item.get("metrics") or {}
        cache_hits = metrics.get("detail_cache_hits")
        live_fetches = metrics.get("detail_live_fetches")
        cache_text = (
            f" cache/live={cache_hits}/{live_fetches}"
            if cache_hits is not None or live_fetches is not None
            else ""
        )
        core_incomplete = metrics.get("detail_core_incomplete")
        core_text = (
            f" core_incomplete={core_incomplete}"
            if core_incomplete is not None else ""
        )
        if source == "popply" and metrics.get("quarantine_count") is not None:
            core_text += (
                f" usable/quarantine={metrics.get('integration_usable_count')}/"
                f"{metrics.get('quarantine_count')}"
            )
        hours_text = ""
        if source == "dayforyou" and metrics.get("operation_hours_coverage") is not None:
            hours_text = (
                f" hours={metrics.get('operation_hours_found')}/"
                f"{(metrics.get('operation_hours_found') or 0) + (metrics.get('operation_hours_missing') or 0)}"
            )
        lines.append(
            f"{source}: count={metrics.get('candidate_count')} "
            f"detail_failed={metrics.get('detail_failed')}"
            f"{cache_text}{core_text}{hours_text} "
            f"llm_calls={metrics.get('llm_calls', 0)}"
        )
    stage_rows = report.get("stages") or []
    if stage_rows:
        lines.append("")
        lines.append("stage_durations:")
        for stage in stage_rows:
            lines.append(f"- {stage.get('name')}: {stage.get('duration_seconds')}s")
    integration = report.get("integration") or {}
    if integration:
        lines.extend([
            "",
            f"canonical={integration.get('canonical_today_count')}",
            f"classification_review={integration.get('classification_review_count')}",
            f"duplicate_review={integration.get('duplicate_review_count')}",
            f"master_committed={integration.get('master_committed')}",
            f"lifecycle={integration.get('lifecycle_counts')}",
        ])
        if integration.get("backend_output_csv"):
            lines.append(
                f"output_csv={integration.get('backend_output_csv')} "
                f"({integration.get('backend_output_count', 0)} rows)"
            )
        changes = integration.get("daily_changes") or {}
        if changes:
            samples = changes.get("samples") or {}

            def names_for(bucket: str) -> str:
                names = [
                    str(item.get("name"))
                    for item in (samples.get(bucket) or [])[:5]
                    if item.get("name")
                ]
                return f" | {', '.join(names)}" if names else ""

            lines.extend([
                "",
                (
                    "daily_changes:"
                    if integration.get("master_committed")
                    else "daily_changes (PROVISIONAL - master not committed):"
                ),
                f"- new={changes.get('new_popup_count', 0)}{names_for('new_popups')}",
                f"- ended={changes.get('newly_ended_count', 0)}{names_for('newly_ended')}",
                f"- reappeared={changes.get('reappeared_count', 0)}{names_for('reappeared')}",
                f"- changed={changes.get('changed_popup_count', 0)}{names_for('changed_popups')}",
                f"- unverified={changes.get('newly_unverified_count', 0)}{names_for('newly_unverified')}",
                f"- source_changes={changes.get('source_change_count', 0)}",
                f"- retired={changes.get('retired_from_master_count', 0)}",
                f"- changed_fields={changes.get('changed_field_counts', {})}",
            ])
    backend_export = report.get("backend_export") or {}
    if backend_export:
        lines.extend([
            "",
            f"backend_json={backend_export.get('output_json')} ({backend_export.get('count', 0)} rows)",
            (
                f"backend_today_hours={backend_export.get('today_hours_count', 0)}/"
                f"{backend_export.get('count', 0)}"
            ),
        ])
    if report.get("errors"):
        lines.extend(["", "errors:", *[f"- {x}" for x in report["errors"]]])
    if report.get("warnings"):
        lines.extend(["", "warnings:", *[f"- {x}" for x in report["warnings"]]])
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    if not (0.0 < args.min_source_retention <= 1.0):
        raise SystemExit("--min-source-retention must be > 0 and <= 1")
    if not (0.0 <= args.max_detail_failure_rate <= 1.0):
        raise SystemExit("--max-detail-failure-rate must be between 0 and 1")

    now = datetime.now(SEOUL_TZ)
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    daily_dir = ROOT / "data" / "daily" / "runs" / timestamp
    daily_dir.mkdir(parents=True, exist_ok=True)
    started_at = now.isoformat(timespec="seconds")
    python = sys.executable

    report: dict[str, Any] = {
        "version": VERSION,
        "status": "RUNNING",
        "started_at": started_at,
        "finished_at": None,
        "daily_date": now.date().isoformat(),
        "reuse_latest": args.reuse_latest,
        "master_commit_requested": not args.no_commit,
        "quality_gate": {
            "min_source_retention": args.min_source_retention,
            "min_source_count": args.min_source_count,
            "max_detail_failure_rate": args.max_detail_failure_rate,
        },
        "sources": {},
        "integration": None,
        "backend_export": None,
        "errors": [],
        "warnings": [],
        "stages": [],
    }

    source_bases = {
        "dayforyou": ROOT / "data" / "runs",
        "popga": ROOT / "data" / "popga" / "runs",
        "popply": ROOT / "data" / "popply" / "runs",
    }
    baseline_reports: dict[str, dict[str, Any] | None] = {}
    baseline_counts: dict[str, int | None] = {}
    for source, base in source_bases.items():
        _, baseline = newest_report(base)
        baseline_reports[source] = baseline
        baseline_counts[source] = source_count_from_report(source, baseline)

    try:
        if args.reuse_latest:
            print("=== v1.0.0 DAILY: 최신 source 결과 재사용 모드 ===")
            source_dirs = {source: newest_run_dir(base) for source, base in source_bases.items()}
            missing = [source for source, path in source_dirs.items() if path is None]
            if missing:
                raise RuntimeError(f"latest source run missing: {', '.join(missing)}")
        else:
            print("=== v1.0.0 DAILY: 3-source fresh crawl ===")
            commands = {
                "dayforyou": [python, "run.py", "--fresh"] + ([] if args.no_llm else ["--execute"]),
                "popga": [python, "run_popga.py", "--details"],
                "popply": [python, "run_popply.py", "--details"],
            }
            source_dirs: dict[str, Path | None] = {}
            stage_failures: list[str] = []

            def record_stage(source: str, stage: StageResult) -> None:
                report["stages"].append(asdict(stage))
                source_dirs[source] = Path(stage.run_dir) if stage.run_dir else None
                if stage.returncode != 0:
                    message = f"{source} stage failed with exit code {stage.returncode}"
                    stage_failures.append(message)
                    report["errors"].append(message)
                    report["sources"][source] = {
                        "run_dir": str(source_dirs[source]) if source_dirs[source] else None,
                        "report": None,
                        "metrics": {"candidate_count": None, "detail_failed": None, "llm_calls": 0},
                        "errors": [message],
                        "warnings": [],
                    }
                elif source_dirs[source] is None:
                    message = f"{source}: output run directory not found"
                    stage_failures.append(message)
                    report["errors"].append(message)
                    report["sources"][source] = {
                        "run_dir": None,
                        "report": None,
                        "metrics": {"candidate_count": None, "detail_failed": None, "llm_calls": 0},
                        "errors": [message],
                        "warnings": [],
                    }

            # DayForYou는 먼저 실행한다. 이후 서로 다른 도메인인 Popga/Popply는
            # 기본적으로 동시에 수집해 전체 wall-clock 시간을 줄인다.
            day_stage = run_stage(
                "dayforyou", commands["dayforyou"], source_bases["dayforyou"],
                output_prefix="[DAYFORYOU] ",
            )
            record_stage("dayforyou", day_stage)

            if args.sequential_sources:
                for source in ("popga", "popply"):
                    stage = run_stage(
                        source, commands[source], source_bases[source],
                        output_prefix=f"[{source.upper()}] ",
                    )
                    record_stage(source, stage)
            else:
                print("\n===== Popga + Popply 병렬 수집 시작 =====", flush=True)
                with ThreadPoolExecutor(max_workers=2) as executor:
                    futures = {
                        executor.submit(
                            run_stage, source, commands[source], source_bases[source],
                            output_prefix=f"[{source.upper()}] ",
                        ): source
                        for source in ("popga", "popply")
                    }
                    completed: dict[str, StageResult] = {}
                    for future in as_completed(futures):
                        source = futures[future]
                        completed[source] = future.result()
                for source in ("popga", "popply"):
                    record_stage(source, completed[source])

            if stage_failures:
                report["status"] = "BLOCKED_SOURCE_STAGE"

        validators = {
            "dayforyou": validate_dayforyou,
            "popga": validate_popga,
            "popply": validate_popply,
        }
        source_outputs: dict[str, Path] = {}
        for source in ("dayforyou", "popga", "popply"):
            run_dir = source_dirs[source]
            if run_dir is None:
                continue
            if not args.reuse_latest and source in report["sources"] and report["sources"][source].get("errors"):
                continue
            source_report, output = _load_source_run(source, run_dir)
            # In reuse mode the latest run is itself the baseline; skip the retention comparison.
            previous_count = None if args.reuse_latest else baseline_counts[source]
            validator_kwargs = dict(
                previous_count=previous_count,
                min_retention=args.min_source_retention,
                min_source_count=args.min_source_count,
                max_detail_failure_rate=args.max_detail_failure_rate,
            )
            if source == "popply":
                validator_kwargs.update(
                    max_core_incomplete_count=args.max_popply_core_incomplete_count,
                    max_core_incomplete_rate=args.max_popply_core_incomplete_rate,
                )
            errors, warnings, metrics = validators[source](
                run_dir, source_report, **validator_kwargs
            )
            # v1.0.0 Popply는 quarantine을 제외한 integration 전용 파일을 사용한다.
            if source == "popply" and metrics.get("output"):
                output = Path(metrics["output"])
            report["sources"][source] = {
                "run_dir": str(run_dir),
                "report": str(run_dir / "report.json"),
                "metrics": metrics,
                "errors": errors,
                "warnings": warnings,
            }
            report["errors"].extend(errors)
            report["warnings"].extend(warnings)
            source_outputs[source] = output

        if report["errors"]:
            if report["status"] == "RUNNING":
                report["status"] = "BLOCKED_SOURCE_QUALITY"
            raise RuntimeError("source stage/quality gate blocked master update")

        integration_command = [
            python,
            "run_integrate.py",
            "--dayforyou", str(source_outputs["dayforyou"]),
            "--popga", str(source_outputs["popga"]),
            "--popply", str(source_outputs["popply"]),
            "--today", report["daily_date"],
        ]
        if not args.no_commit:
            integration_command.append("--commit-master")

        integration_stage = run_stage(
            "integration",
            integration_command,
            ROOT / "data" / "integration" / "runs",
        )
        report["stages"].append(asdict(integration_stage))
        integration_dir = Path(integration_stage.run_dir) if integration_stage.run_dir else None
        if integration_dir is None:
            raise RuntimeError("integration output run directory not found")
        integration_report_path = integration_dir / "run_report.json"
        if not integration_report_path.exists():
            raise RuntimeError("integration run_report.json missing")
        integration_report = read_json(integration_report_path)
        report["integration"] = {
            **integration_report,
            "run_dir": str(integration_dir),
            "report_path": str(integration_report_path),
        }

        if integration_stage.returncode != 0:
            report["status"] = "BLOCKED_INTEGRATION"
            reasons = integration_report.get("master_commit_block_reasons") or []
            report["errors"].extend(str(x) for x in reasons)
            raise RuntimeError(f"integration stage failed with exit code {integration_stage.returncode}")

        if integration_report.get("classification_review_count", 0):
            report["errors"].append(
                f"integration: classification_review={integration_report['classification_review_count']}"
            )
        if integration_report.get("duplicate_review_count", 0):
            report["errors"].append(
                f"integration: duplicate_review={integration_report['duplicate_review_count']}"
            )
        if not args.no_commit and not integration_report.get("master_committed"):
            report["errors"].append("integration: master commit requested but was not committed")

        if report["errors"]:
            report["status"] = "BLOCKED_INTEGRATION"
            raise RuntimeError("integration quality gate blocked master update")

        # Backend adapter is a post-commit delivery step. It does not change
        # crawler/master data; it only converts the successfully exported daily
        # CSV into the backend common place-dict JSON.
        if not args.no_commit and integration_report.get("backend_output_csv"):
            raw_csv_path = str(integration_report["backend_output_csv"])
            csv_path = Path(raw_csv_path)
            if not csv_path.is_absolute():
                csv_path = ROOT / Path(raw_csv_path.replace("\\", os.sep))
            date_prefix = report["daily_date"].replace("-", "")
            backend_json_path = ROOT / "backend_output" / f"{date_prefix}_popup_places.json"
            latest_backend_path = ROOT / "backend_output" / "latest_popup_places.json"
            try:
                backend_export = export_backend_json(
                    csv_path,
                    backend_json_path,
                    latest_path=latest_backend_path,
                )
                report["backend_export"] = backend_export
                latest_export_report = ROOT / "backend_output" / "latest_export_report.json"
                atomic_write_json(latest_export_report, backend_export)
                print(
                    f"Backend JSON: {backend_json_path} "
                    f"({backend_export.get('count', 0)} rows)"
                )
            except Exception as exc:
                report["status"] = "FAILED_BACKEND_EXPORT"
                report["errors"].append(f"backend export failed after master commit: {exc}")
                raise RuntimeError("backend export failed after master commit")

        report["status"] = "SUCCESS_CANDIDATE" if args.no_commit else "SUCCESS"

    except Exception as exc:
        if report["status"] == "RUNNING":
            report["status"] = "FAILED"
        message = str(exc)
        if message and message not in report["errors"]:
            report["errors"].append(message)
    finally:
        report["finished_at"] = datetime.now(SEOUL_TZ).isoformat(timespec="seconds")
        daily_report_path = daily_dir / "daily_report.json"
        atomic_write_json(daily_report_path, report)
        latest_dir = ROOT / "data" / "daily"
        atomic_write_json(latest_dir / "latest_report.json", report)
        integration = report.get("integration") or {}
        changes = integration.get("daily_changes") or {}
        if changes:
            atomic_write_json(daily_dir / "daily_changes.json", changes)
            atomic_write_json(latest_dir / "latest_changes.json", changes)
        summary = _summary_text(report)
        atomic_write_text(daily_dir / "summary.txt", summary)
        atomic_write_text(latest_dir / "latest_summary.txt", summary)

        print()
        print("=== DAILY SUMMARY ===")
        print(summary, end="")
        print(f"daily report: {daily_report_path}")

    if report["status"] not in {"SUCCESS", "SUCCESS_CANDIDATE"}:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
