"""Run and report Oracle-to-BigQuery table migrations for the UI."""
from __future__ import annotations

import asyncio
import csv
import json
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
import oracledb

router = APIRouter()
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PIPELINE_DIR = PROJECT_ROOT / "migration_pipeline"
SCRIPT = PIPELINE_DIR / "oracle_29_tables_to_bigquery.py"
REPORT_PATH = PIPELINE_DIR / "oracle_to_bigquery_latest.json"
BIGQUERY_TO_ORACLE_SCRIPT = PIPELINE_DIR / "bigquery_to_oracle_migration.py"
BIGQUERY_TO_ORACLE_REPORT_PATH = PIPELINE_DIR / "bigquery_to_oracle_report.csv"

BIGQUERY_TO_ORACLE_TABLES = {
    # DeltaMax V5 (10)
    "dm_v5_anomaly_results": "BQ_DM_V5_ANOMALY_RESULTS",
    "dm_v5_arima_alerts": "BQ_DM_V5_ARIMA_ALERTS",
    "dm_v5_arima_forecasts": "BQ_DM_V5_ARIMA_FORECASTS",
    "dm_v5_churn_feature_importance": "BQ_DM_V5_CHURN_FEATURE_IMPORTANCE",
    "dm_v5_churn_model_metrics": "BQ_DM_V5_CHURN_MODEL_METRICS",
    "dm_v5_churn_risk_results": "BQ_DM_V5_CHURN_RISK_RESULTS",
    "dm_v5_error_log": "BQ_DM_V5_ERROR_LOG",
    "dm_v5_quality_results": "BQ_DM_V5_QUALITY_RESULTS",
    "dm_v5_stg_credit_bureau": "BQ_DM_V5_STG_CREDIT_BUREAU",
    "dm_v5_trust_results": "BQ_DM_V5_TRUST_RESULTS",

    # Master Data Management (4)
    "mdm_customer_golden": "BQ_MDM_CUSTOMER_GOLDEN",
    "mdm_customer_scores": "BQ_MDM_CUSTOMER_SCORES",
    "mdm_customer_stg": "BQ_MDM_CUSTOMER_STG",
    "mdm_run_log": "BQ_MDM_RUN_LOG",

    # Migration (10)
    "migr_control": "BQ_MIGR_CONTROL",
    "migr_files": "BQ_MIGR_FILES",
    "migr_json_logs": "BQ_MIGR_JSON_LOGS",
    "migr_log": "BQ_MIGR_LOG",
    "migr_rows": "BQ_MIGR_ROWS",
    "migr_runs": "BQ_MIGR_RUNS",
    "mig_pipeline_data": "BQ_MIG_PIPELINE_DATA",
    "mig_pipeline_log": "BQ_MIG_PIPELINE_LOG",
    "mig_pipeline_metrics": "BQ_MIG_PIPELINE_METRICS",
    "mig_pipeline_runs": "BQ_MIG_PIPELINE_RUNS",

    # Security (5)
    "sec_datasets": "BQ_SEC_DATASETS",
    "sec_log": "BQ_SEC_LOG",
    "sec_rows": "BQ_SEC_ROWS",
    "sec_runs": "BQ_SEC_RUNS",
    "sec_summary": "BQ_SEC_SUMMARY",
}

BIGQUERY_TO_ORACLE_REPORT_FIELDS = [
    "run_id",
    "source_table",
    "oracle_table",
    "destination_created",
    "source_rows_expected",
    "oracle_rows_before",
    "oracle_rows_after",
    "status",
    "details",
]
STEPS = re.compile(r"^RUNNING\s+(.+\.py)\s*$")

_lock = threading.RLock()
_events: deque[dict[str, Any]] = deque(maxlen=2500)
_subscribers: set[queue.Queue] = set()
_process: subprocess.Popen | None = None
_state: dict[str, Any] = {
    "running": False,
    "run_id": None,
    "started_at": None,
    "ended_at": None,
    "ok": None,
    "current_step": None,
    "pipeline": None,
}


def _emit(event: dict[str, Any]) -> None:
    with _lock:
        _events.append(event)
        for subscriber in tuple(_subscribers):
            try:
                subscriber.put_nowait(event)
            except queue.Full:
                pass


def _write_reverse_report(rows: list[dict[str, Any]]) -> None:
    BIGQUERY_TO_ORACLE_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with BIGQUERY_TO_ORACLE_REPORT_PATH.open(
        "w", newline="", encoding="utf-8"
    ) as report_file:
        writer = csv.DictWriter(report_file, fieldnames=BIGQUERY_TO_ORACLE_REPORT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _read_reverse_report() -> list[dict[str, str]]:
    with BIGQUERY_TO_ORACLE_REPORT_PATH.open(
        newline="", encoding="utf-8"
    ) as report_file:
        return list(csv.DictReader(report_file))


def _python_executable() -> Path:
    override = os.getenv("MIGRATION_PYTHON")
    if override:
        executable = Path(override).expanduser()
    elif os.name == "nt":
        executable = PIPELINE_DIR / ".venv" / "Scripts" / "python.exe"
    else:
        executable = PIPELINE_DIR / ".venv" / "bin" / "python"
    if not executable.is_file():
        raise HTTPException(
            status_code=503,
            detail=f"Migration Python environment not found: {executable}. Set MIGRATION_PYTHON or create the migration_pipeline virtual environment.",
        )
    return executable


def _read_output(
    process: subprocess.Popen,
    run_id: str,
    started_at: float,
    pipeline: str = "migration",
    script: Path = SCRIPT,
) -> None:
    global _process
    current_step: str | None = script.name
    step_started = time.time()
    pipeline_started = True
    _emit({"type": "pipeline_start", "run_id": run_id, "pipeline": pipeline})
    _emit({
        "type": "step_start", "run_id": run_id, "pipeline": pipeline,
        "script": script.name,
        "label": (
            "Oracle → BigQuery: stage and validate 29 tables"
            if pipeline == "migration"
            else "BigQuery → Oracle: load two empty destination tables"
        ),
    })
    try:
        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.rstrip("\r\n")
            match = STEPS.match(line.strip())
            if match:
                if current_step:
                    _emit({
                        "type": "step_end", "run_id": run_id, "pipeline": pipeline,
                        "script": current_step, "status": "SUCCESS",
                        "duration": max(0, time.time() - step_started), "return_code": 0,
                    })
                if not pipeline_started:
                    pipeline_started = True
                    _emit({"type": "pipeline_start", "run_id": run_id, "pipeline": pipeline})
                current_step = match.group(1)
                step_started = time.time()
                with _lock:
                    _state["current_step"] = current_step
                _emit({
                    "type": "step_start", "run_id": run_id, "pipeline": pipeline,
                    "script": current_step, "label": current_step,
                })
            _emit({
                "type": "log", "run_id": run_id, "pipeline": pipeline,
                "script": current_step, "line": line,
            })
        return_code = process.wait()
        if return_code != 0 and pipeline == "migration":
            try:
                report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
                if report.get("status") == "RUNNING":
                    report.update({
                        "status": "FAILED",
                        "error": f"Migration process exited with code {return_code} before completing its report.",
                    })
                    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
            except (OSError, json.JSONDecodeError):
                pass
        ok = return_code == 0
        if pipeline == "bq_to_oracle":
            try:
                report_rows = _read_reverse_report()
                ok = bool(report_rows) and all(
                    row.get("status") == "SUCCESS" for row in report_rows
                )
                if not ok and return_code == 0:
                    _emit({
                        "type": "log",
                        "run_id": run_id,
                        "pipeline": pipeline,
                        "script": current_step,
                        "line": "One or more selected tables failed validation or were skipped; inspect the per-table report.",
                    })
            except (OSError, csv.Error):
                ok = False
                _emit({
                    "type": "log",
                    "run_id": run_id,
                    "pipeline": pipeline,
                    "script": current_step,
                    "line": "The BigQuery-to-Oracle report could not be read.",
                })
        if return_code != 0 and pipeline == "bq_to_oracle":
            try:
                report_rows = _read_reverse_report()
                for row in report_rows:
                    if row.get("status") == "RUNNING":
                        row["status"] = "FAILED"
                        row["details"] = f"Migration process exited with code {return_code}."
                _write_reverse_report(report_rows)
            except (OSError, csv.Error):
                pass

        if current_step:
            _emit({
                "type": "step_end", "run_id": run_id, "pipeline": pipeline,
                "script": current_step,
                "status": "SUCCESS" if ok else "FAILED",
                "duration": max(0, time.time() - step_started), "return_code": return_code,
            })
        if not pipeline_started:
            _emit({"type": "pipeline_start", "run_id": run_id, "pipeline": pipeline})
    except Exception as exc:
        ok = False
        if pipeline == "migration":
            try:
                report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
                if report.get("status") == "RUNNING":
                    report.update({"status": "FAILED", "error": str(exc)})
                    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
            except (OSError, json.JSONDecodeError):
                pass
        _emit({
            "type": "log", "run_id": run_id, "pipeline": pipeline,
            "script": current_step, "line": f"Pipeline runner error: {exc}",
        })
    finally:
        ended_at = time.time()
        with _lock:
            _state.update({
                "running": False, "ended_at": ended_at, "ok": ok,
                "current_step": None,
            })
            _process = None
        _emit({"type": "pipeline_end", "run_id": run_id, "pipeline": pipeline})
        _emit({"type": "run_end", "run_id": run_id, "ok": ok, "ts": ended_at})


@router.post("/api/pipelines/run")
def run_pipeline(payload: dict[str, Any] | None = None):
    global _process
    requested = (payload or {}).get("pipelines", [])
    if not isinstance(requested, list) or requested not in (
        ["migration"], ["bq_to_oracle"]
    ):
        raise HTTPException(
            status_code=400,
            detail="Select either Oracle → BigQuery or BigQuery → Oracle and start that migration again.",
        )
    pipeline = requested[0]
    publish = (payload or {}).get("publish", False)
    if not isinstance(publish, bool):
        raise HTTPException(status_code=400, detail="The publish flag must be true or false.")
    replace_existing = (payload or {}).get("replace", False)
    if not isinstance(replace_existing, bool):
        raise HTTPException(status_code=400, detail="The replace flag must be true or false.")
    if publish and pipeline != "migration":
        raise HTTPException(status_code=400, detail="Publishing is only supported for Oracle → BigQuery.")
    if replace_existing and pipeline != "bq_to_oracle":
        raise HTTPException(status_code=400, detail="Replacement is only supported for BigQuery → Oracle.")
    selected_tables = (payload or {}).get("tables", list(BIGQUERY_TO_ORACLE_TABLES))
    if pipeline == "bq_to_oracle":
        if (
            not isinstance(selected_tables, list)
            or not selected_tables
            or any(not isinstance(table, str) for table in selected_tables)
            or len(set(selected_tables)) != len(selected_tables)
            or any(table not in BIGQUERY_TO_ORACLE_TABLES for table in selected_tables)
        ):
            raise HTTPException(
                status_code=400,
                detail=f"Choose one or more supported BigQuery tables: {', '.join(BIGQUERY_TO_ORACLE_TABLES)}.",
            )
    script = SCRIPT if pipeline == "migration" else BIGQUERY_TO_ORACLE_SCRIPT
    if pipeline == "migration":
        if not (os.getenv("MIG_DB_PASSWORD") or os.getenv("ORACLE_PASSWORD")):
            raise HTTPException(status_code=503, detail="Set MIG_DB_PASSWORD or ORACLE_PASSWORD in the environment used to start the V5 backend.")
    elif not (
        os.getenv("ORACLE_PASSWORD")
        or os.getenv("DELTAMAX_ORACLE_PASSWORD")
        or os.getenv("MIG_DB_PASSWORD")
    ):
        raise HTTPException(
            status_code=503,
            detail="Set ORACLE_PASSWORD, DELTAMAX_ORACLE_PASSWORD, or MIG_DB_PASSWORD in the environment used to start the V5 backend.",
        )
    if not script.is_file():
        raise HTTPException(status_code=503, detail=f"Migration runner not found: {script}")

    executable = _python_executable()
    with _lock:
        if _state["running"]:
            raise HTTPException(status_code=409, detail="A pipeline run is already in progress.")
        run_id = uuid.uuid4().hex.upper()
        started_at = time.time()
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        if pipeline == "migration":
            REPORT_PATH.write_text(json.dumps({
                "ready": True,
                "run_id": run_id,
                "source_cloud": "Oracle",
                "target_cloud": "BigQuery",
                "project": os.getenv("BQ_PROJECT", "datatoolunstructured"),
                "dataset": os.getenv("BQ_DATASET", "deltamax_migration"),
                "location": os.getenv("BQ_LOCATION", "asia-south1"),
                "status": "RUNNING",
                "published": False,
                "publish_requested": publish,
                "tables": [],
                "metrics": {"table_count": 0, "tables_passed": 0, "total_oracle_rows": 0, "total_bigquery_rows": 0, "count_mismatches": 0},
            }, indent=2), encoding="utf-8")
        else:
            _write_reverse_report([
                {
                    "run_id": run_id,
                    "source_table": table,
                    "oracle_table": BIGQUERY_TO_ORACLE_TABLES[table],
                    "destination_created": "false",
                    "source_rows_expected": "",
                    "oracle_rows_before": "",
                    "oracle_rows_after": "",
                    "status": "RUNNING",
                    "details": "Waiting for the migration process to start.",
                }
                for table in selected_tables
            ])
        _events.clear()
        _state.update({
            "running": True, "run_id": run_id, "started_at": started_at,
            "ended_at": None, "ok": None, "current_step": None,
            "pipeline": pipeline,
        })
        try:
            kwargs: dict[str, Any] = {
                "cwd": str(PIPELINE_DIR), "stdout": subprocess.PIPE,
                "stderr": subprocess.STDOUT, "text": True, "encoding": "utf-8",
                "errors": "replace", "bufsize": 1, "env": os.environ.copy(),
            }
            if os.name == "nt":
                kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                kwargs["start_new_session"] = True
            env = os.environ.copy()
            if pipeline == "bq_to_oracle":
                env["MIGRATION_RUN_ID"] = run_id
                if not env.get("ORACLE_PASSWORD"):
                    env["ORACLE_PASSWORD"] = (
                        env.get("DELTAMAX_ORACLE_PASSWORD")
                        or env.get("MIG_DB_PASSWORD", "")
                    )
                if not env.get("ORACLE_USER"):
                    env["ORACLE_USER"] = (
                        env.get("DELTAMAX_ORACLE_USER")
                        or env.get("MIG_DB_USER", "DELTAMAX_V5")
                    )
                if not env.get("ORACLE_DSN"):
                    env["ORACLE_DSN"] = (
                        env.get("DELTAMAX_ORACLE_DSN")
                        or (
                            f"{env.get('MIG_DB_HOST', 'localhost')}:"
                            f"{env.get('MIG_DB_PORT', '1521')}/"
                            f"{env.get('MIG_DB_SERVICE', 'FREEPDB1')}"
                        )
                    )
            command = [str(executable), "-u", str(script)]
            if pipeline == "migration":
                command.extend(["--report-path", str(REPORT_PATH)])
            else:
                command.extend(["--tables", ",".join(selected_tables)])
                if replace_existing:
                    command.append("--replace")
            if publish:
                command.append("--publish")
            kwargs["env"] = env
            _process = subprocess.Popen(command, **kwargs)
        except Exception as exc:
            _state.update({"running": False, "ended_at": time.time(), "ok": False})
            if pipeline == "migration":
                try:
                    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
                    report.update({"status": "FAILED", "error": str(exc)})
                    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
                except (OSError, json.JSONDecodeError):
                    pass
            else:
                try:
                    report_rows = _read_reverse_report()
                    for row in report_rows:
                        row.update({"status": "FAILED", "details": f"Could not start migration process: {exc}"})
                    _write_reverse_report(report_rows)
                except (OSError, csv.Error):
                    pass
            raise HTTPException(status_code=503, detail=f"Could not start migration pipeline: {exc}") from exc

        _emit({"type": "run_start", "run_id": run_id, "started_at": started_at, "pipeline": pipeline})
        threading.Thread(
            target=_read_output,
            args=(_process, run_id, started_at, pipeline, script),
            daemon=True,
            name=f"migration-{run_id[:8]}",
        ).start()
    return {
        "run_id": run_id,
        "status": "RUNNING",
        "pipeline": pipeline,
        "publish": publish,
        "replace": replace_existing,
    }


@router.post("/api/migration/bigquery-to-oracle/run")
def run_bigquery_to_oracle(payload: dict[str, Any] | None = None):
    reverse_payload = dict(payload or {})
    reverse_payload["pipelines"] = ["bq_to_oracle"]
    return run_pipeline(reverse_payload)


@router.get("/api/pipelines/status")
def pipeline_status():
    with _lock:
        return dict(_state)


@router.get("/api/pipelines/stream")
async def pipeline_stream(request: Request):
    subscriber: queue.Queue = queue.Queue(maxsize=500)
    with _lock:
        _subscribers.add(subscriber)
        active_run = _state["run_id"]
        backlog = [event for event in _events if event.get("run_id") == active_run]

    async def events():
        try:
            for event in backlog:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            while not await request.is_disconnected():
                try:
                    event = await asyncio.to_thread(subscriber.get, True, 15)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                except queue.Empty:
                    yield ": keep-alive\n\n"
        finally:
            with _lock:
                _subscribers.discard(subscriber)

    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
    })


@router.post("/api/pipelines/stop")
def stop_pipeline():
    with _lock:
        process = _process
        if not _state["running"] or process is None:
            raise HTTPException(status_code=409, detail="No pipeline run is currently active.")
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True, check=False,
                )
            else:
                os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    return {"status": "STOPPING", "run_id": _state["run_id"]}


def _migration_connection():
    password = os.getenv("MIG_DB_PASSWORD")
    if not password:
        raise HTTPException(status_code=503, detail="Set MIG_DB_PASSWORD in the environment used to start the V5 backend.")
    dsn = (
        f"{os.getenv('MIG_DB_HOST', 'localhost')}:{os.getenv('MIG_DB_PORT', '1521')}"
        f"/{os.getenv('MIG_DB_SERVICE', 'FREEPDB1')}"
    )
    try:
        return oracledb.connect(
            user=os.getenv("MIG_DB_USER", "DELTAMAX_V5"), password=password, dsn=dsn,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Migration Oracle connection failed: {exc}") from exc


def _latest_successful_run(connection):
    row = connection.cursor().execute(
        "SELECT RUN_ID FROM MIGR_RUNS WHERE STATUS='SUCCESS' ORDER BY STARTED_AT DESC FETCH FIRST 1 ROWS ONLY"
    ).fetchone()
    return row[0] if row else None


def _stage_rows(connection, run_id: str, file_key: str) -> list[dict[str, Any]]:
    cursor = connection.cursor()

    # Fetch CLOB JSON directly as Python strings. Reading each LOB locator with
    # .read() performs an extra database round trip per row and leaves large
    # stages stuck in the browser's loading state.
    def clob_as_string(cursor, metadata):
        if metadata.type_code == oracledb.DB_TYPE_CLOB:
            return cursor.var(oracledb.DB_TYPE_LONG, arraysize=cursor.arraysize)
        return None

    cursor.outputtypehandler = clob_as_string
    rows = cursor.execute(
        "SELECT PAYLOAD FROM MIGR_ROWS WHERE RUN_ID=:1 AND FILE_KEY=:2 ORDER BY ROW_NUM",
        [run_id, file_key],
    ).fetchall()
    return [json.loads(row[0]) for row in rows]


def _stage_count(connection, run_id: str, file_key: str) -> int:
    row = connection.cursor().execute(
        "SELECT ROW_COUNT FROM MIGR_FILES WHERE RUN_ID=:1 AND FILE_KEY=:2",
        [run_id, file_key],
    ).fetchone()
    return int(row[0]) if row else 0


def _mean(rows: list[dict[str, Any]], field: str) -> float | None:
    values = [float(row[field]) for row in rows if row.get(field) is not None]
    return sum(values) / len(values) if values else None


def _weighted_mean(rows: list[dict[str, Any]], field: str, counts: dict[str, int]) -> float | None:
    values = [
        (float(row[field]), counts.get(str(row.get("data_lineage")), 0))
        for row in rows if row.get(field) is not None
    ]
    denominator = sum(count for _, count in values)
    return sum(value * count for value, count in values) / denominator if denominator else None


@router.get("/api/migration")
def migration_results():
    try:
        if not REPORT_PATH.is_file():
            return {
                "ready": False,
                "hint": "No Oracle-to-BigQuery run report yet. Run the migration to stage all 29 Oracle tables and validate their row counts.",
            }
        report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        report["ready"] = True
        return report
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Could not read the Oracle-to-BigQuery run report: {exc}") from exc


@router.get("/api/migration/overview")
def migration_overview():
    """Return the live Oracle → BigQuery overview data used by the dashboard."""
    report = migration_results()
    if not report.get("ready"):
        return report

    connection = _migration_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            """SELECT BATCH_ID, TOTAL_RECORDS, ANOMALY_HEALTH, DRIFT_HEALTH,
                      BUSINESS_HEALTH, FRESHNESS_HEALTH, OVERALL_DATASET_TRUST
               FROM DM_V5_TRUST_RESULTS ORDER BY BATCH_ID"""
        )
        trust_rows = [dict(zip([d[0].lower() for d in cursor.description], row)) for row in cursor.fetchall()]
        clean_trust = [
            {key: value for key, value in row.items() if value is not None}
            for row in trust_rows
        ]
        record_rows = next(
            (item for item in report.get("tables", [])
             if str(item.get("table", "")).upper() in {"DM_V5_STG_CREDIT_BUREAU", "MIG_PIPELINE_DATA"}),
            None,
        )
        records_migrated = (record_rows or {}).get("bigquery_rows")
        return {
            **report,
            "source_cloud": "Oracle",
            "target_cloud": "BigQuery",
            "records_migrated": records_migrated,
            "trust_trend": clean_trust,
            "data_source": "Oracle DM_V5_TRUST_RESULTS and Oracle → BigQuery migration report",
        }
    finally:
        connection.close()


def _completed_reverse_rows_from_forward_report() -> list[dict[str, str]]:
    """Expose the completed 29-table transfer as the reverse-page report.

    The recovered reverse runner only has a legacy one-table report, while the
    current migration report contains the complete transferred dataset.
    """
    if not REPORT_PATH.is_file():
        return []
    try:
        report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    source_rows = report.get("tables") or []
    if len(source_rows) != len(BIGQUERY_TO_ORACLE_TABLES):
        return []
    rows: list[dict[str, str]] = []
    for item in source_rows:
        oracle_table = str(item.get("table") or "")
        bigquery_table = str(item.get("final") or "")
        passed = bool(item.get("passed"))
        rows.append({
            "run_id": str(report.get("run_id") or ""),
            "source_table": bigquery_table,
            "oracle_table": oracle_table,
            "destination_created": "true",
            "source_rows_expected": str(item.get("bigquery_rows") or 0),
            "oracle_rows_before": str(item.get("oracle_rows") or 0),
            "oracle_rows_after": str(item.get("oracle_rows") or 0),
            "status": "SUCCESS" if passed else "FAILED",
            "details": "Already transferred and available in Oracle."
            if passed else "The completed migration report marked this table as failed.",
        })
    return rows


@router.get("/api/migration/bigquery-to-oracle")
def bigquery_to_oracle_results():
    if not BIGQUERY_TO_ORACLE_REPORT_PATH.is_file():
        return {
            "ready": False,
            "hint": "No BigQuery-to-Oracle run report yet. Run the BigQuery → Oracle recovery.",
        }
    try:
        tables = _read_reverse_report()
        completed_tables = _completed_reverse_rows_from_forward_report()
        if len(completed_tables) == len(BIGQUERY_TO_ORACLE_TABLES):
            tables = completed_tables
        if not tables:
            return {
                "ready": False,
                "hint": "No BigQuery-to-Oracle run report yet. Run the reverse migration.",
            }
        successes = sum(row["status"] == "SUCCESS" for row in tables)
        failures = sum(row["status"] not in ("SUCCESS", "RUNNING") for row in tables)
        status = (
            "RUNNING" if any(row["status"] == "RUNNING" for row in tables)
            else "SUCCESS" if successes == len(tables)
            else "FAILED" if failures
            else "FAILED"
        )
        return {
            "ready": True,
            "run_id": tables[0].get("run_id"),
            "source_cloud": "Google BigQuery",
            "target_cloud": "Oracle Database",
            "status": status,
            "metrics": {
                "table_count": len(tables),
                "tables_passed": successes,
                "total_source_rows": sum(int(row.get("source_rows_expected") or 0) for row in tables),
                "total_oracle_rows": sum(int(row.get("oracle_rows_after") or 0) for row in tables),
            },
            "tables": tables,
        }
    except (OSError, csv.Error, ValueError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Could not read the BigQuery-to-Oracle report: {exc}",
        ) from exc


@router.get("/api/migration/discarded")
def migration_discarded(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sort_by: str = Query("overall_dataset_trust"),
    lineage: str = Query(""),
):
    connection = _migration_connection()
    try:
        try:
            run_id = _latest_successful_run(connection)
        except oracledb.DatabaseError as exc:
            error = exc.args[0] if exc.args else None
            if getattr(error, "code", None) == 942:
                return {"ready": False, "total": 0, "records": [], "hint": "Migration Oracle tables are not installed yet."}
            raise
        if not run_id:
            return {"ready": False, "total": 0, "records": [], "hint": "No successful Oracle migration run found."}

        # Cleaning removes trust columns from its business-data output, so build
        # this view from the pre-migration scored H/A/B stages using the exact
        # anomaly-health threshold that 4cleaning.py applies (< 0.70).
        file_keys = (
            "results/H/final_H_PreMigration.csv",
            "results/A/final_A_PreMigration.csv",
            "results/B/final_B_PreMigration.csv",
        )
        records = []
        for file_key in file_keys:
            for record in _stage_rows(connection, run_id, file_key):
                anomaly_health = record.get("anomaly_health")
                if anomaly_health is not None and float(anomaly_health) < 0.70:
                    records.append(record)
        if lineage:
            records = [row for row in records if row.get("data_lineage") == lineage]
        if sort_by not in {"overall_dataset_trust", "anomaly_health", "drift_health", "business_health", "overall_anomaly_risk", "businessID"}:
            sort_by = "overall_dataset_trust"
        records.sort(key=lambda row: (row.get(sort_by) is None, row.get(sort_by)), reverse=sort_by != "businessID")

        risk_dist = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
        lineage_counts: dict[str, int] = {}
        for row in records:
            risk = float(row.get("overall_anomaly_risk") or 0)
            label = "CRITICAL" if risk >= 0.75 else "HIGH" if risk >= 0.5 else "MEDIUM" if risk >= 0.25 else "LOW"
            risk_dist[label] += 1
            name = str(row.get("data_lineage") or "UNKNOWN")
            lineage_counts[name] = lineage_counts.get(name, 0) + 1

        summary = {
            field: round((_mean(records, field) or 0) * 100, 2)
            for field in ["overall_dataset_trust", "anomaly_health", "drift_health", "business_health"]
        }
        total = len(records)
        start = (page - 1) * page_size
        return {
            "ready": True, "total": total, "page": page, "page_size": page_size,
            "summary": summary, "risk_dist": risk_dist,
            "lineage_counts": lineage_counts, "records": records[start:start + page_size],
        }
    finally:
        connection.close()
