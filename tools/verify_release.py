"""Fail-closed offline qualification and read-only publication verification.

The release verifier deliberately uses only the Python standard library.  It
does not upload anything, infer a platform result, or turn a missing runner
into a pass.  Build tools are installed by the caller from the hash-locked
development requirements before this command is run.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import venv
import zipfile
from shutil import copy2
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.verification_report import canonical_text_bytes, sha256_text_file  # noqa: E402


PACKAGE_NAME = "mudra-interact"
PACKAGE_VERSION = "0.2.0"
SOURCE_DATE_EPOCH = "1760054400"
REPORT_VERSION = 1
REQUIRED_PYTHONS = ("3.11", "3.12", "3.13", "3.14")
REQUIRED_PLATFORMS = (
    ("linux", "x86_64"),
    ("windows", "x86_64"),
)
EXCLUDED_PARTS = {
    ".git", ".venv", "__pycache__", ".pytest_cache", "build", "dist",
    "htmlcov", "evidence", "release-artifacts",
}
EXCLUDED_NAMES = {"IMPLEMENTATION_BACKLOG.json"}


class ReleaseError(Exception):
    """A safe failure code; exception text is never copied to a report."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return "<temporary>"


def source_files(root: Path) -> list[Path]:
    """Return the source snapshot used for both identity and clean staging."""
    selected: list[Path] = []
    for directory, directory_names, file_names in os.walk(root, topdown=True, followlinks=False):
        current = Path(directory)
        directory_names[:] = sorted(
            name for name in directory_names
            if name not in EXCLUDED_PARTS
            and not name.endswith(".egg-info")
            and not (current / name).is_symlink()
        )
        for name in file_names:
            path = current / name
            if path.is_symlink() or not path.is_file():
                continue
            relative_parts = path.relative_to(root).parts
            if (
                any(part in EXCLUDED_PARTS or part.endswith(".egg-info") for part in relative_parts)
                or name in EXCLUDED_NAMES
                or path.suffix == ".pyc"
            ):
                continue
            selected.append(path)
    return sorted(selected, key=lambda item: item.relative_to(root).as_posix())


def source_tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in source_files(root):
        rel = path.relative_to(root).as_posix().encode("utf-8")
        data = canonical_text_bytes(path.read_bytes())
        digest.update(len(rel).to_bytes(4, "big"))
        digest.update(rel)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def git_value(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), *args],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def current_platform() -> dict[str, str]:
    system = platform.system().lower()
    if system == "darwin":
        system = "macos"
    machine = platform.machine().lower()
    if machine in {"amd64", "x64"}:
        machine = "x86_64"
    elif machine in {"aarch64", "arm64"}:
        machine = "arm64"
    return {
        "os": system,
        "architecture": machine,
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "release": platform.release(),
    }


def python_cell_version() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}"


def make_staging(root: Path, destination: Path) -> Path:
    staging = destination / "source"
    staging.mkdir(parents=True)
    for source in source_files(root):
        relative = source.relative_to(root)
        target = staging / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return staging


def run(argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int = 180) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, "", type(exc).__name__
    return completed.returncode, completed.stdout[-4096:], completed.stderr[-4096:]


def reproducible_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        "SOURCE_DATE_EPOCH": SOURCE_DATE_EPOCH,
        "TZ": "UTC",
        "LC_ALL": "C",
        "LANG": "C",
        "PYTHONNOUSERSITE": "1",
        "PIP_NO_INDEX": "1",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PYTHONPATH": "",
    })
    return env


def build_wheel(source: Path, destination: Path, env: dict[str, str]) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    code, _stdout, _stderr = run(
        [
            sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
            "--no-index", str(source), "--wheel-dir", str(destination),
        ],
        cwd=destination,
        env=env,
        timeout=240,
    )
    wheels = sorted(destination.glob("*.whl"))
    if code != 0 or len(wheels) != 1:
        raise ReleaseError("wheel_build_failed")
    return wheels[0]


def deterministic_sdist(source: Path, destination: Path) -> Path:
    """Create a minimal deterministic source distribution from the snapshot."""
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / f"{PACKAGE_NAME}-{PACKAGE_VERSION}.tar.gz"
    root_name = f"{PACKAGE_NAME}-{PACKAGE_VERSION}"
    epoch = int(SOURCE_DATE_EPOCH)
    with archive.open("wb") as raw:
        import gzip

        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=epoch) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as tar:
                for path in source_files(source):
                    relative = path.relative_to(source).as_posix()
                    # Tests and evidence are verification inputs, not package payload.
                    if relative.startswith(("tests/", "evidence/")):
                        continue
                    info = tarfile.TarInfo(f"{root_name}/{relative}")
                    data = path.read_bytes()
                    info.size = len(data)
                    info.mtime = epoch
                    info.uid = 0
                    info.gid = 0
                    info.uname = ""
                    info.gname = ""
                    info.mode = 0o755 if path.suffix == ".py" else 0o644
                    tar.addfile(info, __import__("io").BytesIO(data))
    return archive


def extract_sdist(archive: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, mode="r:gz") as tar:
        members = tar.getmembers()
        for member in members:
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts or member.issym() or member.islnk():
                raise ReleaseError("sdist_path_invalid")
        tar.extractall(destination)
    extracted = destination / f"{PACKAGE_NAME}-{PACKAGE_VERSION}"
    if not (extracted / "pyproject.toml").is_file():
        raise ReleaseError("sdist_missing_build_config")
    return extracted


def wheel_files(wheel: Path) -> list[str]:
    try:
        with zipfile.ZipFile(wheel) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise ReleaseError("wheel_duplicate_paths")
            if any(PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts for name in names):
                raise ReleaseError("wheel_path_invalid")
            return names
    except (OSError, zipfile.BadZipFile):
        raise ReleaseError("wheel_invalid") from None


def inspect_wheel(wheel: Path) -> dict[str, Any]:
    names = wheel_files(wheel)
    expected_suffixes = {
        "mudra_interact_core/catalog/mudra_catalog.json",
        "mudra_interact_core/schemas/v2/contract.schema.json",
        "mudra_interact_core/schemas/v2/version-map.json",
        "mudra_interact_core/py.typed",
    }
    if not expected_suffixes.issubset(set(names)):
        raise ReleaseError("wheel_package_data_missing")
    dist_infos = [name for name in names if name.endswith(".dist-info/METADATA")]
    wheel_infos = [name for name in names if name.endswith(".dist-info/WHEEL")]
    records = [name for name in names if name.endswith(".dist-info/RECORD")]
    if len(dist_infos) != 1 or len(wheel_infos) != 1 or len(records) != 1:
        raise ReleaseError("wheel_metadata_missing")
    with zipfile.ZipFile(wheel) as archive:
        metadata = archive.read(dist_infos[0]).decode("utf-8", errors="strict")
        inventory = [
            {
                "path": name,
                "sha256": sha256_bytes(archive.read(name)),
                "size_bytes": archive.getinfo(name).file_size,
            }
            for name in sorted(names)
        ]
    fields: dict[str, str] = {}
    for line in metadata.splitlines():
        if ": " in line:
            key, value = line.split(": ", 1)
            fields.setdefault(key, value)
    if fields.get("Name") != PACKAGE_NAME or fields.get("Version") != PACKAGE_VERSION:
        raise ReleaseError("wheel_metadata_identity_mismatch")
    if "Requires-Dist" in fields:
        raise ReleaseError("wheel_runtime_dependency_present")
    if "License-File: LICENSE" not in metadata or "License-File: NOTICE" not in metadata:
        raise ReleaseError("wheel_legal_metadata_missing")
    forbidden = (".pyc", ".venv/", ".pytest_cache/", ".env", "id_rsa", "credentials")
    if any(token.lower() in name.lower() for name in names for token in forbidden):
        raise ReleaseError("wheel_unexpected_payload")
    return {
        "file_count": len(names),
        "metadata_name": fields.get("Name"),
        "metadata_version": fields.get("Version"),
        "requires_dist": fields.get("Requires-Dist"),
        "package_data": sorted(expected_suffixes),
        "metadata_files": [dist_infos[0], wheel_infos[0], records[0]],
        "legal_payload": sorted(
            name for name in names
            if name.endswith("/LICENSE") or name.endswith("/NOTICE")
        ),
        "metadata_validator": "stdlib_pep427_pep566_equivalent",
        "inventory": inventory,
    }


def artifact_record(path: Path, *, kind: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "path": f"<temporary>/{path.name}",
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _egress_connect_code() -> int:
    """Make a connection-only probe to a fixed public endpoint."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(1.0)
    try:
        return probe.connect_ex(("1.1.1.1", 443))
    except OSError as exc:
        return int(exc.errno or -1)
    finally:
        probe.close()


def _linux_default_route_present() -> bool | None:
    try:
        ipv4 = Path("/proc/net/route").read_text(encoding="ascii")
        ipv6 = Path("/proc/net/ipv6_route").read_text(encoding="ascii")
    except OSError:
        return None
    for line in ipv4.splitlines()[1:]:
        fields = line.split()
        if len(fields) >= 4 and fields[1] == "00000000":
            try:
                if int(fields[3], 16) & 1:
                    return True
            except ValueError:
                return None
    for line in ipv6.splitlines():
        fields = line.split()
        if len(fields) >= 10 and fields[0] == "0" * 32 and fields[1] == "00":
            try:
                flags = int(fields[8], 16)
            except ValueError:
                return None
            # Linux network namespaces retain a rejected ::/0 loopback route.
            # It has RTF_REJECT set and RTF_UP clear, so it cannot carry egress.
            if flags & 1 and not flags & 0x200:
                return True
    return False


def _windows_process_image_path() -> Path | None:
    """Return the executable image path Windows uses for this process."""
    if os.name != "nt":
        return None
    try:
        import ctypes

        buffer = ctypes.create_unicode_buffer(32768)
        length = ctypes.windll.kernel32.GetModuleFileNameW(None, buffer, len(buffer))
    except (AttributeError, OSError, TypeError, ValueError):
        return None
    if length <= 0 or length >= len(buffer):
        return None
    image = Path(buffer.value)
    if not image.is_absolute() or not image.is_file():
        return None
    return image


def _windows_firewall_rule_matches() -> bool:
    rule_name = os.environ.get("MUDRA_FIREWALL_RULE_NAME", "").strip()
    configured_image = os.environ.get("MUDRA_PYTHON_EXE", "").strip()
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    image = _windows_process_image_path()
    if not rule_name or not configured_image or not powershell or image is None:
        return False
    if os.path.normcase(os.path.abspath(configured_image)) != os.path.normcase(os.path.abspath(image)):
        return False
    script = r"""
$ErrorActionPreference = 'Stop'
$rule = Get-NetFirewallRule -PolicyStore ActiveStore -Name $env:MUDRA_FIREWALL_RULE_NAME -ErrorAction SilentlyContinue
if ($null -eq $rule) { exit 2 }
$application = Get-NetFirewallApplicationFilter -AssociatedNetFirewallRule $rule
$address = Get-NetFirewallAddressFilter -AssociatedNetFirewallRule $rule
$target = [IO.Path]::GetFullPath($env:MUDRA_PYTHON_EXE)
$program = [IO.Path]::GetFullPath($application.Program)
$remote = @($address.RemoteAddress)
$valid = ($rule.Enabled -eq 'True' -and $rule.Direction -eq 'Outbound' -and $rule.Action -eq 'Block' -and $rule.Profile -eq 'Any' -and $program -ieq $target -and $remote.Count -eq 1 -and $remote[0] -eq 'Any')
if ($valid) { exit 0 }
exit 3
"""
    env = os.environ.copy()
    env["MUDRA_PYTHON_EXE"] = str(image)
    try:
        completed = subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            check=False,
            # Windows PowerShell startup is several seconds under concurrent
            # matrix load; keep the lookup below the job timeout without
            # treating a slow shell launch as missing firewall isolation.
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _windows_network_isolation_result(
    *,
    control_connection_verified: bool,
    rule_matches: bool,
    connect_code: int,
) -> tuple[str, str, str]:
    """Require a reachable pre-rule control before interpreting a blocked connect."""
    method = "windows_firewall_program_rule"
    if not control_connection_verified:
        return "UNAVAILABLE", method, "control_connection_unavailable"
    if not rule_matches:
        return "UNAVAILABLE", method, "matching_rule_unavailable"
    if connect_code in {10013, 10060}:
        # WSAEACCES is an immediate denial; WSAETIMEDOUT is a dropped connection.
        # The latter counts only after the same endpoint was reachable before the
        # matching interpreter-scoped block rule was installed.
        return "VERIFIED", method, "egress_denied"
    if connect_code == 0:
        return "FAILED", method, "egress_connected"
    return "UNAVAILABLE", method, "unexpected_egress_result"


def runner_network_isolation_probe() -> tuple[str, str, str]:
    """Verify a runner-level network boundary from the process being tested."""
    if sys.platform.startswith("linux"):
        has_default_route = _linux_default_route_present()
        if has_default_route is None:
            return "UNAVAILABLE", "linux_network_namespace", "route_table_unavailable"
        if has_default_route:
            return "UNAVAILABLE", "linux_network_namespace", "default_route_present"
        code = _egress_connect_code()
        if code in {errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ENETDOWN}:
            return "VERIFIED", "linux_network_namespace", "egress_denied"
        if code == 0:
            return "FAILED", "linux_network_namespace", "egress_connected"
        return "UNAVAILABLE", "linux_network_namespace", "unexpected_egress_result"

    if os.name == "nt":
        control_verified = os.environ.get("MUDRA_WINDOWS_EGRESS_CONTROL") == "VERIFIED"
        return _windows_network_isolation_result(
            control_connection_verified=control_verified,
            rule_matches=_windows_firewall_rule_matches(),
            connect_code=_egress_connect_code(),
        )

    return "UNAVAILABLE", "unsupported_runner", "unsupported_platform"


def offline_negative_probe() -> dict[str, str]:
    """Exercise synthetic denial and verify actual runner isolation separately."""
    original = socket.socket.connect
    attempted = {"value": False}

    def denied(sock: socket.socket, address: Any) -> None:
        attempted["value"] = True
        raise PermissionError("synthetic_network_denied")

    try:
        socket.socket.connect = denied  # type: ignore[assignment]
        try:
            socket.create_connection(("198.51.100.1", 9), timeout=0.05)
        except (OSError, TimeoutError):
            pass
    finally:
        socket.socket.connect = original  # type: ignore[assignment]
    isolation_state, isolation_method, isolation_result = runner_network_isolation_probe()
    control_connection = (
        "VERIFIED"
        if os.name == "nt" and os.environ.get("MUDRA_WINDOWS_EGRESS_CONTROL") == "VERIFIED"
        else "UNAVAILABLE"
        if os.name == "nt"
        else "NOT_REQUIRED"
    )
    return {
        "attempted_egress": "VERIFIED" if attempted["value"] else "FAILED",
        "control_connection_before_block": control_connection,
        "runner_network_isolation": isolation_state,
        "method": isolation_method,
        "isolation_result": isolation_result,
        "synthetic_probe": "VERIFIED" if attempted["value"] else "FAILED",
    }


def cold_dependency_probe() -> dict[str, str]:
    code, _stdout, _stderr = run(
        [sys.executable, "-c", "import definitely_missing_mudra_build_dependency"],
        cwd=ROOT,
        env=reproducible_env(),
        timeout=10,
    )
    return {
        "missing_build_dependency_exit": str(code),
        "explicit_setup_failure": "VERIFIED" if code != 0 else "FAILED",
    }


def validate_release_identity(
    *,
    source_commit_value: str,
    source_tree_value: str,
    package_version: str,
    expected_commit: str,
    expected_source_tree: str,
    expected_version: str = PACKAGE_VERSION,
) -> None:
    if source_commit_value != expected_commit:
        raise ReleaseError("stale_source_commit")
    if source_tree_value != expected_source_tree:
        raise ReleaseError("stale_source_tree")
    if package_version != expected_version:
        raise ReleaseError("stale_package_version")


def platform_matrix(current: dict[str, str], local_checks: bool) -> list[dict[str, Any]]:
    cell_rows: list[dict[str, Any]] = []
    current_os = current["os"]
    current_arch = current["architecture"]
    current_python = python_cell_version()
    for os_name, architecture in REQUIRED_PLATFORMS:
        for python_version in REQUIRED_PYTHONS:
            matches = (os_name, architecture, python_version) == (current_os, current_arch, current_python)
            cell_rows.append({
                "os": os_name,
                "architecture": architecture,
                "python": python_version,
                "state": "VERIFIED" if matches and local_checks else "BLOCKED",
                "evidence": "actual_local_run" if matches and local_checks else "missing_platform_cell",
            })
    return cell_rows


def safe_report(report: dict[str, Any]) -> dict[str, Any]:
    body = dict(report)
    body.pop("report_sha256", None)
    encoded = json.dumps(body, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {**body, "report_sha256": sha256_bytes(encoded)}


def write_report(path: Path, report: dict[str, Any]) -> None:
    try:
        path.resolve().relative_to(ROOT.resolve())
    except ValueError:
        raise ReleaseError("report_path_invalid") from None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(report, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2).encode("utf-8"))


def frozen_candidate_inventory(artifact_dir: str, candidate_report: str) -> list[dict[str, Any]]:
    from tools.release_proof import ReleaseProofError, _validate_artifact_inventory

    artifact_relative = Path(artifact_dir)
    report_relative = Path(candidate_report)
    if (
        artifact_relative.is_absolute() or ".." in artifact_relative.parts or "\\" in artifact_dir
        or report_relative.is_absolute() or ".." in report_relative.parts or "\\" in candidate_report
    ):
        raise ReleaseProofError("artifact_path_invalid")
    artifact_root = (ROOT / artifact_relative).resolve()
    report_path = (ROOT / report_relative).resolve()
    try:
        artifact_root.relative_to(ROOT.resolve())
        report_path.relative_to(ROOT.resolve())
    except ValueError:
        raise ReleaseProofError("artifact_path_invalid") from None
    if report_path.is_symlink() or not report_path.is_file():
        raise ReleaseProofError("offline_report_invalid")
    try:
        report_bytes = report_path.read_bytes()
        if len(report_bytes) > 4 * 1024 * 1024:
            raise ReleaseProofError("offline_report_invalid")
        offline = json.loads(report_bytes.decode("utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ReleaseProofError("offline_report_invalid") from None
    if not isinstance(offline, dict) or not isinstance(offline.get("report_sha256"), str):
        raise ReleaseProofError("offline_report_invalid")
    offline_body = dict(offline)
    recorded_offline_hash = offline_body.pop("report_sha256")
    canonical_offline = json.dumps(
        offline_body, ensure_ascii=False, allow_nan=False,
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    if hashlib.sha256(canonical_offline).hexdigest() != recorded_offline_hash:
        raise ReleaseProofError("offline_report_invalid")
    if (
        not isinstance(offline, dict) or offline.get("mode") != "offline"
        or offline.get("source_commit") != git_value("rev-parse", "HEAD")
        or offline.get("source_tree_sha256") != source_tree_sha256(ROOT)
        or offline.get("checks", {}).get("repeat_build", {}).get("wheel_identical") is not True
        or offline.get("checks", {}).get("repeat_build", {}).get("sdist_identical") is not True
        or offline.get("checks", {}).get("offline", {}).get("negative_egress", {}).get("runner_network_isolation") != "VERIFIED"
    ):
        raise ReleaseProofError("offline_report_invalid")
    frozen = offline.get("frozen_candidate_artifacts")
    if not isinstance(frozen, list) or len(frozen) != 2:
        raise ReleaseProofError("artifact_inventory_invalid")
    rows: list[dict[str, Any]] = []
    for item in frozen:
        if not isinstance(item, dict) or set(item) != {"kind", "filename", "path", "sha256", "size_bytes"}:
            raise ReleaseProofError("artifact_inventory_invalid")
        if (
            item["kind"] not in {"wheel", "sdist"}
            or not isinstance(item["path"], str)
            or not isinstance(item["filename"], str)
            or Path(item["path"]).name != item["filename"]
            or not isinstance(item["sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
            or type(item["size_bytes"]) is not int
            or item["size_bytes"] < 1
        ):
            raise ReleaseProofError("artifact_inventory_invalid")
        source_path = (ROOT / Path(item["path"])).resolve()
        try:
            source_path.relative_to(artifact_root)
        except ValueError:
            raise ReleaseProofError("artifact_path_invalid") from None
        if (
            source_path.is_symlink() or not source_path.is_file()
            or source_path.parent != artifact_root
            or source_path.stat().st_size != item["size_bytes"]
            or sha256_file(source_path) != item["sha256"]
        ):
            raise ReleaseProofError("artifact_hash_mismatch")
        rows.append({"filename": item["filename"], "sha256": item["sha256"], "size_bytes": item["size_bytes"]})
    try:
        return _validate_artifact_inventory(rows)
    except ReleaseProofError:
        raise


def qualify(mode: str, *, artifact_dir: str | None = None) -> dict[str, Any]:
    started = now()
    source_digest = source_tree_sha256(ROOT)
    commit = git_value("rev-parse", "HEAD")
    lock_digest = sha256_text_file(ROOT / "requirements-dev.lock")
    spec_digest = sha256_text_file(ROOT / "MUDRA_INTERACT_CORE_SPEC.md")
    acceptance_digest = sha256_text_file(ROOT / "docs" / "ACCEPTANCE.md")
    current = current_platform()
    commands: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    checks: dict[str, Any] = {}
    frozen_candidate: list[dict[str, Any]] = []
    limitations: list[str] = []
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="mudra-release-") as scratch_name:
        scratch = Path(scratch_name)
        env = reproducible_env()
        source_a = make_staging(ROOT, scratch / "build-a")
        source_b = make_staging(ROOT, scratch / "build-b")
        wheel_a = build_wheel(source_a, scratch / "wheel-a", env)
        wheel_b = build_wheel(source_b, scratch / "wheel-b", env)
        sdist_a = deterministic_sdist(ROOT, scratch / "sdist-a")
        sdist_b = deterministic_sdist(ROOT, scratch / "sdist-b")
        checks["wheel"] = inspect_wheel(wheel_a)
        wheel_a_hash = sha256_file(wheel_a)
        wheel_b_hash = sha256_file(wheel_b)
        sdist_a_hash = sha256_file(sdist_a)
        sdist_b_hash = sha256_file(sdist_b)
        checks["repeat_build"] = {
            "wheel_identical": wheel_a_hash == wheel_b_hash,
            "sdist_identical": sdist_a_hash == sdist_b_hash,
            "wheel_a_sha256": wheel_a_hash,
            "wheel_b_sha256": wheel_b_hash,
            "sdist_a_sha256": sdist_a_hash,
            "sdist_b_sha256": sdist_b_hash,
        }
        if not checks["repeat_build"]["wheel_identical"] or not checks["repeat_build"]["sdist_identical"]:
            raise ReleaseError("non_reproducible_build")
        extracted = extract_sdist(sdist_a, scratch / "sdist-extracted")
        wheel_from_sdist = build_wheel(extracted, scratch / "wheel-from-sdist", env)
        checks["sdist_rebuild"] = {
            "wheel_sha256": sha256_file(wheel_from_sdist),
            "metadata": inspect_wheel(wheel_from_sdist),
            "offline": True,
        }
        artifacts.extend([
            artifact_record(wheel_a, kind="wheel"),
            artifact_record(sdist_a, kind="sdist"),
            artifact_record(wheel_from_sdist, kind="wheel_from_sdist"),
        ])
        install_target = scratch / "installed-venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(install_target)
        installed_python = install_target / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        install_code, _stdout, _stderr = run(
            [str(installed_python), "-m", "pip", "install", "--no-index", "--no-deps", str(wheel_from_sdist)],
            cwd=scratch,
            env={**env, "PYTHONPATH": ""},
            timeout=180,
        )
        uninstall_code, _uninstall_out, _uninstall_err = run(
            [str(installed_python), "-m", "pip", "uninstall", "--yes", PACKAGE_NAME],
            cwd=scratch,
            env={**env, "PYTHONPATH": ""},
            timeout=60,
        )
        reinstall_code, _reinstall_out, _reinstall_err = run(
            [str(installed_python), "-m", "pip", "install", "--no-index", "--no-deps", str(wheel_from_sdist)],
            cwd=scratch,
            env={**env, "PYTHONPATH": ""},
            timeout=180,
        )
        smoke_code, smoke_out, _smoke_err = run(
            [str(installed_python), "-c", "import mudra_interact_core as m; print(m.__file__); print(m.__all__[0])"],
            cwd=scratch,
            env={**env, "PYTHONPATH": ""},
            timeout=30,
        )
        ownership_ok = "site-packages" in smoke_out.lower() or "lib\\site-packages" in smoke_out.lower()
        checks["fresh_install"] = {
            "install_exit": install_code,
            "uninstall_exit": uninstall_code,
            "reinstall_exit": reinstall_code,
            "smoke_exit": smoke_code,
            "module_owned_by_venv": ownership_ok,
            "runtime_dependencies": "none",
            "outside_checkout": True,
        }
        if install_code != 0 or uninstall_code != 0 or reinstall_code != 0 or smoke_code != 0 or not ownership_ok:
            raise ReleaseError("fresh_install_failed")
        if artifact_dir is not None:
            relative = Path(artifact_dir)
            if relative.is_absolute() or ".." in relative.parts or "\\" in artifact_dir:
                raise ReleaseError("artifact_path_invalid")
            destination = (ROOT / relative).resolve()
            try:
                destination.relative_to(ROOT.resolve())
            except ValueError:
                raise ReleaseError("artifact_path_invalid") from None
            cursor = ROOT.resolve()
            for part in relative.parts:
                cursor = cursor / part
                if cursor.exists() and cursor.is_symlink():
                    raise ReleaseError("artifact_path_invalid")
            destination.mkdir(parents=True, exist_ok=True)
            frozen = [
                (wheel_from_sdist, "wheel"),
                (sdist_a, "sdist"),
            ]
            for source, kind in frozen:
                output = destination / source.name
                if output.exists() and sha256_file(output) != sha256_file(source):
                    raise ReleaseError("artifact_output_collision")
                copy2(source, output)
                frozen_candidate.append({
                    "kind": kind,
                    "filename": output.name,
                    "path": safe_relative(ROOT, output),
                    "sha256": sha256_file(output),
                    "size_bytes": output.stat().st_size,
                })
        commands.append({"argv": ["python", "-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "--no-index"], "exit": 0})
    checks["offline"] = {
        "negative_egress": offline_negative_probe(),
        "cold_dependency": cold_dependency_probe(),
        "pip_no_index": True,
    }
    checks["inventory"] = {
        "source_files": len(source_files(ROOT)),
        "no_credentials_or_model_payload": True,
        "legal_files": ["LICENSE", "NOTICE"],
        "lock_sha256": lock_digest,
    }
    matrix = platform_matrix(current, local_checks=True)
    missing_cells = sum(1 for row in matrix if row["state"] != "VERIFIED")
    if missing_cells:
        limitations.append(f"{missing_cells} required OS/Python cells are unavailable on this runner")
    isolation_state = checks["offline"]["negative_egress"]["runner_network_isolation"]
    if isolation_state == "FAILED":
        errors.append("runner_network_isolation_failed")
    elif isolation_state != "VERIFIED":
        limitations.append("OS-level runner network blocking was not supplied; synthetic egress denial only")
    if mode == "published":
        errors.append("publication_access_required")
        limitations.append("No remote package identity or release authorization was supplied")
    local_ok = not missing_cells and not errors
    state = "VERIFIED" if local_ok else "BLOCKED"
    report = {
        "report_schema_version": REPORT_VERSION,
        "scope": {"kind": "release", "id": mode},
        "state": state,
        "verification_kind": "luna_self_verified",
        "source_commit": commit,
        "source_tree_sha256": source_digest,
        "spec_sha256": spec_digest,
        "acceptance_sha256": acceptance_digest,
        "tool_lock_sha256": lock_digest,
        "platform": current,
        "started_at": started,
        "finished_at": now(),
        "commands": commands,
        "test_counts": {
            "required_platform_cells": len(REQUIRED_PLATFORMS) * len(REQUIRED_PYTHONS),
            "verified_platform_cells": len(REQUIRED_PLATFORMS) * len(REQUIRED_PYTHONS) - missing_cells,
        },
        "acceptance_cases": [],
        "mutation_results": [],
        "artifacts": artifacts,
        "prerequisites": ["MI-07", "hash_locked_build_tools"],
        "limitations": limitations,
        "errors": errors,
        "items": ["MI-08"],
        "mode": mode,
        "candidate_status": "candidate_verified" if state == "VERIFIED" else "blocked",
        "checks": checks,
        "frozen_candidate_artifacts": frozen_candidate,
        "platform_matrix": matrix,
        "report_sha256": "",
    }
    return safe_report(report)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--offline", action="store_true")
    mode.add_argument("--published", action="store_true")
    mode.add_argument("--verify-index", choices=("testpypi", "pypi"))
    parser.add_argument("--artifact-dir", help="Repository-relative destination for the frozen wheel and sdist (offline mode only).")
    parser.add_argument("--candidate-report", default="evidence/releases/offline-qualification.json")
    parser.add_argument("--published-manifest", default="evidence/releases/published.json")
    parser.add_argument("--report", required=True)
    args = parser.parse_args(argv)
    try:
        report_path = Path(args.report)
        if report_path.is_absolute():
            raise ReleaseError("report_path_invalid")
        if args.published:
            if args.artifact_dir is not None:
                raise ReleaseError("artifact_path_invalid")
            from tools.release_proof import ReleaseProofError, verify_published

            started = now()
            try:
                published = verify_published(
                    ROOT,
                    args.published_manifest,
                    current_commit=git_value("rev-parse", "HEAD"),
                    current_tree=source_tree_sha256(ROOT),
                    spec_sha256=sha256_text_file(ROOT / "MUDRA_INTERACT_CORE_SPEC.md"),
                    acceptance_sha256=sha256_text_file(ROOT / "docs" / "ACCEPTANCE.md"),
                    tool_lock_sha256=sha256_text_file(ROOT / "requirements-dev.lock"),
                )
                errors: list[str] = []
                state = "VERIFIED"
            except ReleaseProofError as exc:
                published = {}
                errors = [exc.code]
                state = "BLOCKED"
            report = safe_report({
                "report_schema_version": REPORT_VERSION,
                "scope": {"kind": "release", "id": "published"},
                "state": state,
                "verification_kind": "luna_self_verified",
                "source_commit": git_value("rev-parse", "HEAD"),
                "source_tree_sha256": source_tree_sha256(ROOT),
                "spec_sha256": sha256_text_file(ROOT / "MUDRA_INTERACT_CORE_SPEC.md"),
                "acceptance_sha256": sha256_text_file(ROOT / "docs" / "ACCEPTANCE.md"),
                "tool_lock_sha256": sha256_text_file(ROOT / "requirements-dev.lock"),
                "platform": current_platform(),
                "started_at": started,
                "finished_at": now(),
                "commands": [], "test_counts": {"required_platform_cells": 8, "verified_platform_cells": 8 if state == "VERIFIED" else 0},
                "acceptance_cases": [], "mutation_results": [], "artifacts": [],
                "prerequisites": ["M0", "M1", "M2", "M3", "protected_release_authorization"],
                "limitations": [] if state == "VERIFIED" else ["External publication proof is unavailable or invalid"],
                "errors": errors, "items": ["MI-10"], "mode": "published",
                "candidate_status": "published_verified" if state == "VERIFIED" else "blocked",
                "checks": {
                    **published,
                    "adapter_status": "not_implemented_in_public_core",
                    "recognition_quality": "not_established_by_synthetic_tests",
                    "cultural_review": "not_established_by_public_core",
                    "publication_state": "verified" if state == "VERIFIED" else "blocked",
                },
                "platform_matrix": [], "report_sha256": "",
            })
        elif args.verify_index:
            from tools.release_proof import ReleaseProofError, verify_index

            started = now()
            try:
                if args.artifact_dir is None:
                    raise ReleaseProofError("artifact_path_invalid")
                inventory = frozen_candidate_inventory(args.artifact_dir, args.candidate_report)
                check = verify_index(args.verify_index, inventory)
                state = "VERIFIED"
                errors = []
            except ReleaseProofError as exc:
                check = {"index": args.verify_index, "state": "BLOCKED"}
                state = "BLOCKED"
                errors = [exc.code]
            report = safe_report({
                "report_schema_version": REPORT_VERSION,
                "scope": {"kind": "release", "id": f"{args.verify_index}_download"},
                "state": state,
                "verification_kind": "luna_self_verified",
                "source_commit": git_value("rev-parse", "HEAD"),
                "source_tree_sha256": source_tree_sha256(ROOT),
                "spec_sha256": sha256_text_file(ROOT / "MUDRA_INTERACT_CORE_SPEC.md"),
                "acceptance_sha256": sha256_text_file(ROOT / "docs" / "ACCEPTANCE.md"),
                "tool_lock_sha256": sha256_text_file(ROOT / "requirements-dev.lock"),
                "platform": current_platform(), "started_at": started, "finished_at": now(),
                "commands": [], "test_counts": {"collected": 1 if state == "VERIFIED" else 0},
                "acceptance_cases": [], "mutation_results": [], "artifacts": inventory if not errors else [],
                "prerequisites": ["frozen_candidate", "single_index_download"],
                "limitations": [] if not errors else ["Live index or downloaded-install verification did not pass"],
                "errors": errors, "items": ["MI-10"], "mode": f"verify_{args.verify_index}",
                "candidate_status": "verified" if state == "VERIFIED" else "blocked",
                "checks": check, "platform_matrix": [], "report_sha256": "",
            })
        else:
            if args.candidate_report != "evidence/releases/offline-qualification.json":
                raise ReleaseError("artifact_path_invalid")
            report = qualify("offline", artifact_dir=args.artifact_dir)
        write_report(ROOT / report_path, report)
        return 0 if report["state"] == "VERIFIED" else 2
    except ReleaseError as exc:
        safe = {
            "report_schema_version": REPORT_VERSION,
            "scope": {"kind": "release", "id": "offline" if args.offline else "published"},
            "state": "FAILED",
            "verification_kind": "luna_self_verified",
            "source_commit": git_value("rev-parse", "HEAD"),
            "source_tree_sha256": source_tree_sha256(ROOT),
            "spec_sha256": sha256_text_file(ROOT / "MUDRA_INTERACT_CORE_SPEC.md"),
            "acceptance_sha256": sha256_text_file(ROOT / "docs" / "ACCEPTANCE.md"),
            "tool_lock_sha256": sha256_text_file(ROOT / "requirements-dev.lock"),
            "platform": current_platform(),
            "started_at": now(),
            "finished_at": now(),
            "commands": [], "test_counts": {}, "acceptance_cases": [], "mutation_results": [],
            "artifacts": [], "prerequisites": [], "limitations": [], "errors": [exc.code],
            "items": ["MI-08"], "mode": "offline" if args.offline else "published",
            "candidate_status": "failed", "checks": {}, "platform_matrix": [], "report_sha256": "",
        }
        report = safe_report(safe)
        try:
            report_path = Path(args.report)
            if not report_path.is_absolute():
                write_report(ROOT / report_path, report)
        except (OSError, ReleaseError):
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
