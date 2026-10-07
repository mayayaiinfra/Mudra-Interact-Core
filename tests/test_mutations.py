from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.acceptance("E69")
def test_required_semantic_mutations_are_detected_in_isolated_copies(tmp_path: Path) -> None:
    report = tmp_path / "mutations.json"
    result = subprocess.run(
        [sys.executable, "tools/run_mutations.py", "--report", str(report), "--timeout-seconds", "90"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert result.returncode == 0, result.stdout[-1000:] + result.stderr[-1000:]
    document = json.loads(report.read_text(encoding="utf-8"))
    assert document["state"] == "VERIFIED"
    assert document["source_tree_sha256_before"] == document["source_tree_sha256_after"]
    assert len(document["mutation_results"]) == 15
    assert all(item["applied"] and item["detected"] for item in document["mutation_results"])
