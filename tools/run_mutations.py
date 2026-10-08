"""Run the auditable semantic mutation proof without editing the real checkout."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {".git", ".venv", "__pycache__", ".pytest_cache", "build", "dist", "evidence"}


@dataclass(frozen=True)
class Mutation:
    name: str
    target: str
    old: str
    new: str
    assertions: tuple[str, ...]
    nodes: tuple[str, ...] = ()
    custom_assertion: str | None = None


MUTATIONS = (
    Mutation(
        "truthy_consent",
        "src/mudra_interact_core/session.py",
        "if type(consent_confirmed) is not bool or consent_confirmed is not True:",
        "if not consent_confirmed:",
        ("E38", "E46"),
        ("tests/test_consent.py", "tests/test_cli.py::test_event_requires_both_explicit_flags_and_emits_one_event"),
    ),
    Mutation(
        "rejected_advances_streak",
        "src/mudra_interact_core/session.py",
        "if result.state is not RecognitionState.CANDIDATE:",
        "if result.state is RecognitionState.CANDIDATE:",
        ("E32",),
        ("tests/test_session.py::test_uncertain_and_low_score_inputs_clear_the_streak",),
    ),
    Mutation(
        "duplicate_identity_allowed",
        "src/mudra_interact_core/session.py",
        "if self._last_frame_id is not None and parsed.frame_id <= self._last_frame_id:\n                self._clear_streak(\"invalid_sequence\")\n                fail(\"invalid_sequence\")\n            if self._last_frame_time is not None and parsed.monotonic_ms <= self._last_frame_time:",
        "if self._last_frame_id is not None and parsed.frame_id < self._last_frame_id:\n                self._clear_streak(\"invalid_sequence\")\n                fail(\"invalid_sequence\")\n            if self._last_frame_time is not None and parsed.monotonic_ms < self._last_frame_time:",
        ("E33",),
        ("tests/test_session.py::test_sequence_watermarks_require_strict_ids_and_times",),
    ),
    Mutation(
        "hold_time_removed",
        "src/mudra_interact_core/session.py",
        "elif parsed.monotonic_ms - self._streak_start < self.config.minimum_hold_ms:",
        "elif False:",
        ("E31",),
        ("tests/test_session.py::test_high_rate_frames_cannot_bypass_hold_and_memory_is_bounded",),
    ),
    Mutation(
        "consumed_confirmation_reused",
        "src/mudra_interact_core/session.py",
        "if self._consumed_revision == self._revision:\n            self._clear_streak()\n            fail(\"stale_confirmation\")",
        "if False:\n            self._clear_streak()\n            fail(\"stale_confirmation\")",
        ("E39", "E40", "E41"),
        ("tests/test_consent.py::test_one_emission_per_confirmed_revision", "tests/test_consent.py::test_confirmation_age_and_monotonic_clock_boundaries"),
    ),
    Mutation(
        "boolean_coordinate_coercion",
        "src/mudra_interact_core/validation.py",
        "if type(value) not in (int, float):\n        fail(\"invalid_shape\")\n    if isinstance(value, float) and not math.isfinite(value):",
        "if not isinstance(value, (int, float)):\n        fail(\"invalid_shape\")\n    if isinstance(value, float) and not math.isfinite(value):",
        ("E11", "E12"),
        ("tests/test_validation.py",),
    ),
    Mutation(
        "strict_contact_predicate",
        "src/mudra_interact_core/recognition.py",
        '"thumb_index": self.thumb_index <= threshold,\n            "thumb_middle": self.thumb_middle <= threshold,\n            "thumb_ring": self.thumb_ring <= threshold,',
        '"thumb_index": self.thumb_index < threshold,\n            "thumb_middle": self.thumb_middle < threshold,\n            "thumb_ring": self.thumb_ring < threshold,',
        ("E21",),
        ("tests/test_recognition.py::test_contact_threshold_is_inclusive",),
    ),
    Mutation(
        "aspect_conversion_removed",
        "src/mudra_interact_core/frame.py",
        "factor = self.image_height / self.image_width  # type: ignore[operator]",
        "factor = 1.0",
        ("E23", "E24"),
        ("tests/test_coordinates.py::test_portrait_and_landscape_image_spaces_match_cartesian_oracle",),
    ),
    Mutation(
        "metadata_extra_allowed",
        "src/mudra_interact_core/protocol.py",
        "if type(self.metadata) is not dict or self.metadata:",
        "if type(self.metadata) is not dict:",
        ("E62",),
        ("tests/test_privacy.py::test_event_boundary_rejects_raw_data_and_prose_at_each_closed_nesting_point",),
    ),
    Mutation(
        "duplicate_json_keys_allowed",
        "src/mudra_interact_core/validation.py",
        "object_pairs_hook=_pairs_no_duplicates,",
        "object_pairs_hook=None,",
        ("E15", "E16"),
        ("tests/test_json_boundary.py",),
    ),
    Mutation(
        "licence_inventory_bypassed",
        "tools_check_license_allowlist.py",
        "return _inventory_errors(root, relative_inventory, components, allowed)",
        "return []",
        ("E67", "E68"),
        ("tests/test_licensing.py",),
    ),
    Mutation(
        "receipt_hash_ignored",
        "tools/verification_report.py",
        "if sha256_file(resolved) != expected_sha256:",
        "if False and sha256_file(resolved) != expected_sha256:",
        ("E80",),
        custom_assertion="stale_receipt",
    ),
    Mutation(
        "solo_release_admin_bypass_allowed",
        "tools/release_proof.py",
        'or body.get("can_admins_bypass") is not False',
        "or False",
        ("E94",),
        ("tests/test_release_recovery.py::test_production_environment_requires_solo_owner_manual_approval_main_only_and_no_bypass",),
    ),
    Mutation(
        "solo_release_branch_scope_ignored",
        "tools/release_proof.py",
        'and branch_policies[0].get("name") == "main"',
        "and True",
        ("E94",),
        ("tests/test_release_recovery.py::test_production_environment_requires_solo_owner_manual_approval_main_only_and_no_bypass",),
    ),
    Mutation(
        "solo_release_self_approval_policy_reversed",
        "tools/release_proof.py",
        "or prevent_self_review is not False",
        "or prevent_self_review is not True",
        ("E94",),
        ("tests/test_release_recovery.py::test_production_environment_requires_solo_owner_manual_approval_main_only_and_no_bypass",),
    ),
)


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    paths: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in EXCLUDED for part in relative.parts) or relative.name.endswith(".pyc"):
            continue
        if relative.as_posix() == "IMPLEMENTATION_BACKLOG.json":
            continue
        paths.append(path)
    for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        contents = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(contents).to_bytes(8, "big"))
        digest.update(contents)
    return digest.hexdigest()


def _copy_root(destination: Path) -> None:
    shutil.copytree(
        ROOT,
        destination,
        ignore=shutil.ignore_patterns(".git", ".venv", "evidence", "build", "dist", ".pytest_cache", "__pycache__"),
    )


def _run(nodes: tuple[str, ...], cwd: Path, *, timeout: float) -> tuple[int, str]:
    environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    environment["PYTHONPATH"] = os.pathsep.join((str(cwd / "src"), str(cwd)))
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--tb=short", "--maxfail=1", *nodes],
            cwd=cwd,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        return 124, f"mutation_test_timeout:{type(error).__name__}"
    output = result.stdout or ""
    return result.returncode, output[-4096:]


def _custom_assertion(root: Path, name: str) -> tuple[int, str]:
    if name != "stale_receipt":
        return 2, "unknown_custom_assertion"
    script = root / "mutation_assert_stale_receipt.py"
    script.write_text(
        "from pathlib import Path\n"
        "import json\n"
        "from tools.verification_report import seal_report, validate_receipt_file, VerificationError\n"
        "report = seal_report({'report_schema_version': 1, 'scope': {'kind': 'item', 'id': 'MI-01'}, 'state': 'VERIFIED', 'verification_kind': 'luna_self_verified', 'source_commit': 'a'*40, 'source_tree_sha256': '1'*64, 'spec_sha256': '2'*64, 'acceptance_sha256': '3'*64, 'tool_lock_sha256': '4'*64, 'platform': {'os': 'windows'}, 'started_at': '2026-10-07T00:00:00.000000Z', 'finished_at': '2026-10-07T00:00:01.000000Z', 'commands': [], 'test_counts': {'collected': 1, 'passed': 1, 'failed': 0, 'skipped': 0, 'xfailed': 0, 'xpassed': 0}, 'acceptance_cases': [{'acceptance_id': 'E80', 'outcome': 'passed', 'node_id': 'synthetic'}], 'mutation_results': [], 'artifacts': [], 'prerequisites': [], 'limitations': [], 'errors': [], 'items': ['MI-01']})\n"
        "path = Path('mutation-receipt.json')\n"
        "path.write_text(json.dumps(report, sort_keys=True, separators=(',', ':')), encoding='utf-8')\n"
        "try:\n"
        "    validate_receipt_file(Path('.').resolve(), path.name, '0'*64, required_case_ids={'E80'})\n"
        "except VerificationError as error:\n"
        "    assert error.code == 'receipt_file_hash_mismatch'\n"
        "else:\n"
        "    raise AssertionError('tampered receipt was accepted')\n",
        encoding="utf-8",
    )
    try:
        result = subprocess.run([sys.executable, script.name], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=20, check=False)
    except subprocess.TimeoutExpired:
        return 124, "custom_assertion_timeout"
    return result.returncode, (result.stdout or "")[-4096:]


def _infrastructure_failure(output: str) -> bool:
    markers = ("SyntaxError", "ImportError", "ModuleNotFoundError", "No module named", "INTERNALERROR", "collected 0 items")
    return any(marker in output for marker in markers)


def run(timeout: float = 90.0) -> dict[str, object]:
    selected_nodes = tuple(dict.fromkeys(node for mutation in MUTATIONS for node in mutation.nodes))
    before = _tree_digest(ROOT)
    baseline_code, baseline_output = _run(selected_nodes, ROOT, timeout=timeout)
    results: list[dict[str, object]] = []
    infrastructure_errors: list[str] = []
    if baseline_code != 0:
        return {
            "schema_version": 1,
            "state": "FAILED",
            "verification_kind": "luna_self_verified",
            "source_tree_sha256_before": before,
            "source_tree_sha256_after": _tree_digest(ROOT),
            "baseline_exit_code": baseline_code,
            "baseline_output_sha256": hashlib.sha256(baseline_output.encode()).hexdigest(),
            "mutation_results": [],
            "errors": ["baseline_tests_failed"],
        }
    with tempfile.TemporaryDirectory(prefix="mudra-mutation-") as temporary:
        temporary_root = Path(temporary)
        for mutation in MUTATIONS:
            mutant_root = temporary_root / re.sub(r"[^A-Za-z0-9_-]", "_", mutation.name)
            _copy_root(mutant_root)
            target = mutant_root / mutation.target
            try:
                source = target.read_text(encoding="utf-8")
                occurrences = source.count(mutation.old)
                if occurrences != 1:
                    results.append({"name": mutation.name, "applied": False, "detected": False, "error": "target_occurrence_mismatch"})
                    infrastructure_errors.append(mutation.name)
                    continue
                target.write_text(source.replace(mutation.old, mutation.new, 1), encoding="utf-8")
            except (OSError, UnicodeError) as error:
                results.append({"name": mutation.name, "applied": False, "detected": False, "error": type(error).__name__})
                infrastructure_errors.append(mutation.name)
                continue
            if mutation.custom_assertion:
                code, output = _custom_assertion(mutant_root, mutation.custom_assertion)
            else:
                code, output = _run(mutation.nodes, mutant_root, timeout=timeout)
            detected = code != 0 and not _infrastructure_failure(output)
            if not detected:
                infrastructure_errors.append(mutation.name)
            results.append({
                "name": mutation.name,
                "target": mutation.target,
                "assertions": list(mutation.assertions),
                "applied": True,
                "exit_code": code,
                "detected": detected,
                "output_sha256": hashlib.sha256(output.encode()).hexdigest(),
                "output_excerpt": output.replace(str(mutant_root), "<mutant>")[-512:],
            })
    after = _tree_digest(ROOT)
    errors = list(infrastructure_errors)
    if before != after:
        errors.append("real_source_tree_changed")
    return {
        "schema_version": 1,
        "state": "VERIFIED" if not errors and all(result.get("detected") for result in results) else "FAILED",
        "verification_kind": "luna_self_verified",
        "source_tree_sha256_before": before,
        "source_tree_sha256_after": after,
        "baseline_exit_code": baseline_code,
        "mutation_results": results,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Mudra semantic mutations in isolated copies.")
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    args = parser.parse_args(argv)
    report = run(timeout=max(1.0, args.timeout_seconds))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({"state": report["state"], "errors": report["errors"]}, sort_keys=True))
    return 0 if report["state"] == "VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
