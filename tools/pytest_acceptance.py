"""Pytest plugin that records actual acceptance-marked test executions."""

from __future__ import annotations

import json
import hashlib
import math
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _safe_parameter(value: Any) -> Any:
    if value is None or type(value) in {bool, int}:
        return {"type": type(value).__name__, "value": value}
    if type(value) is float:
        if not math.isfinite(value):
            return {"type": "float", "value": "non_finite"}
        return {"type": "float", "value": value}
    if type(value) is str:
        encoded = value.encode("utf-8", errors="replace")
        return {"type": "str", "length": len(value), "sha256": hashlib.sha256(encoded).hexdigest()}
    return {"type": type(value).__name__}


def pytest_addoption(parser: Any) -> None:
    parser.addoption("--acceptance-report", action="store", default=None)


def pytest_configure(config: Any) -> None:
    global _ACTIVE_CONFIG
    _ACTIVE_CONFIG = config
    config.addinivalue_line("markers", "acceptance(case_id): required acceptance case identifier")
    config._mudra_acceptance_started_at = _timestamp()
    config._mudra_acceptance_nodes = {}
    config._mudra_acceptance_phase_reports = {}


def pytest_collection_finish(session: Any) -> None:
    nodes: dict[str, dict[str, Any]] = session.config._mudra_acceptance_nodes
    for item in session.items:
        markers = list(item.iter_markers(name="acceptance"))
        case_id = None
        if len(markers) == 1 and markers[0].args:
            candidate = markers[0].args[0]
            if type(candidate) is str:
                case_id = candidate
        callspec = getattr(item, "callspec", None)
        params = {}
        parameter_id = None
        if callspec is not None:
            parameter_id = hashlib.sha256(callspec.id.encode("utf-8", errors="replace")).hexdigest()[:16]
            params = {str(key)[:80]: _safe_parameter(value) for key, value in callspec.params.items()}
        safe_node_id = f"{item.location[0]}::{getattr(item, 'originalname', item.name)}"
        if parameter_id is not None:
            safe_node_id += f"[{parameter_id}]"
        nodes[item.nodeid] = {
            "node_id": safe_node_id[:512],
            "acceptance_id": case_id,
            "parameter_id": parameter_id,
            "parameters": params,
            "phases": [],
            "outcome": "not_executed",
        }


def pytest_runtest_logreport(report: Any) -> None:
    _record_phase(report)


_ACTIVE_CONFIG: Any = None


def _append_report(report: Any, reports: dict[str, list[dict[str, Any]]]) -> None:
    if report.when not in {"setup", "call", "teardown"}:
        return
    was_xfail = getattr(report, "wasxfail", None)
    outcome = report.outcome
    if was_xfail is not None:
        outcome = "xfailed" if outcome == "skipped" else "xpassed"
    reports.setdefault(report.nodeid, []).append({"phase": report.when, "outcome": outcome})


def _record_phase(report: Any) -> None:
    if _ACTIVE_CONFIG is not None:
        _append_report(report, _ACTIVE_CONFIG._mudra_acceptance_phase_reports)


def pytest_sessionfinish(session: Any, exitstatus: int) -> None:
    config = session.config
    nodes = config._mudra_acceptance_nodes
    phases = config._mudra_acceptance_phase_reports
    result_nodes = []
    for node_id, node in nodes.items():
        phase_reports = phases.get(node_id, [])
        node["phases"] = phase_reports
        outcomes = {phase["outcome"] for phase in phase_reports}
        if "xpassed" in outcomes:
            node["outcome"] = "xpassed"
        elif "failed" in outcomes:
            node["outcome"] = "failed"
        elif "xfailed" in outcomes:
            node["outcome"] = "xfailed"
        elif "skipped" in outcomes:
            node["outcome"] = "skipped"
        elif "passed" in outcomes:
            node["outcome"] = "passed"
        result_nodes.append(node)
    report_path = config.getoption("--acceptance-report")
    if not report_path:
        return
    document = {
        "report_schema_version": 1,
        "complete": True,
        "pytest_exit_status": int(exitstatus),
        "started_at": config._mudra_acceptance_started_at,
        "finished_at": _timestamp(),
        "collected_count": len(nodes),
        "nodes": result_nodes,
    }
    destination = Path(report_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(document, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    fd, temporary_name = tempfile.mkstemp(prefix=".acceptance-", suffix=".tmp", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, destination)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def pytest_unconfigure(config: Any) -> None:
    global _ACTIVE_CONFIG
    if _ACTIVE_CONFIG is config:
        _ACTIVE_CONFIG = None
