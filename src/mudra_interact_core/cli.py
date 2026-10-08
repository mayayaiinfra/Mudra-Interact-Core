"""Fail-closed local command line interface for Mudra Interact Core.

The CLI is deliberately a thin boundary around the validated public API. It
never discovers files, accepts stdin or URLs, writes input data, or treats a
JSON value as consent. Successful output is built before one write so a
non-zero exit is always an unsuccessful operation.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Sequence

from .errors import MudraValidationError
from .frame import Frame, parse_batch, parse_frame
from .protocol import InteractionParty, RecognitionState, parse_event
from .session import RecognitionSession
from .validation import (
    MAX_BATCH_BYTES,
    MAX_EVENT_BYTES,
    MAX_FRAME_BYTES,
    SCHEMA_VERSION,
    fail,
    parse_json_bytes,
    require_canonical_uuid,
)


EXIT_OK = 0
EXIT_USAGE = 2
EXIT_DENIED = 3
EXIT_IO = 4
EXIT_INTERRUPTED = 130
_OUTPUT_LIMIT = 512
_VERSION_FALLBACK = "0.3.0"
_REASON_PRECEDENCE = (
    "unsupported_pattern",
    "ambiguous_contacts",
    "low_confidence",
    "gesture_changed",
    "frame_gap",
    "hold_incomplete",
    "insufficient_frames",
)


class _UsageError(Exception):
    """An argparse error whose user input must not be echoed."""


class _OutputError(Exception):
    """The selected output stream failed, including a partial write."""


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise _UsageError


def _package_version() -> str:
    try:
        return version("mudra-interact")
    except PackageNotFoundError:
        return _VERSION_FALLBACK


def _build_parser() -> _ArgumentParser:
    parser = _ArgumentParser(
        prog="mudra-interact",
        description="Run offline v2 landmark recognition and validate image-free events.",
        add_help=False,
        allow_abbrev=False,
    )
    parser.add_argument("command", nargs="?", choices=("recognize", "validate-event"))
    parser.add_argument("--help", action="store_true", help="show this help and exit")
    parser.add_argument("--version", action="store_true", help="show the installed package version and exit")
    parser.add_argument("--input", dest="input_path")
    parser.add_argument("--stabilize", action="store_true", help="process a bounded frame batch through one session")
    parser.add_argument("--emit-event", action="store_true", help="emit one event after explicit consent and confirmation")
    parser.add_argument("--consent", action="store_true", help="explicitly attest sharing consent for this selected batch")
    parser.add_argument("--confirm", action="store_true", help="explicitly attest participant confirmation for this selected batch")
    parser.add_argument("--sender", default=None, help="event sender: human or agent")
    parser.add_argument("--recipient", default=None, help="event recipient: human or agent")
    parser.add_argument("--conversation-id", default=None)
    parser.add_argument("--project-id", default=None)
    return parser


def _write_stream(stream: Any, data: bytes) -> None:
    """Write all bytes exactly once; never retry a failed or partial write."""

    target = getattr(stream, "buffer", stream)
    try:
        written = target.write(data)
    except TypeError:
        # Test harnesses may provide a text-only stream. Real CLI streams are
        # binary and therefore never take this branch.
        try:
            written = target.write(data.decode("utf-8"))
        except (BrokenPipeError, OSError, UnicodeError) as exc:
            raise _OutputError from exc
    except (BrokenPipeError, OSError, UnicodeError) as exc:
        raise _OutputError from exc
    if written is not None and written != len(data):
        raise _OutputError
    flush = getattr(target, "flush", None)
    if callable(flush):
        try:
            flush()
        except (BrokenPipeError, OSError) as exc:
            raise _OutputError from exc


def _emit_error(code: str) -> None:
    payload = json.dumps({"error": {"code": code}}, separators=(",", ":"), ensure_ascii=True).encode("ascii") + b"\n"
    if len(payload) > _OUTPUT_LIMIT:
        return
    try:
        _write_stream(sys.stderr, payload)
    except _OutputError:
        # A broken diagnostic pipe must not trigger a traceback or a retry.
        return


def _emit_success(payload: bytes) -> int:
    try:
        _write_stream(sys.stdout, payload + b"\n")
    except _OutputError:
        return EXIT_IO
    return EXIT_OK


def _is_explicit_remote_or_special(text: str) -> str | None:
    if not text or text == "-":
        return "input_unavailable"
    lowered = text.lower()
    if "://" in lowered or lowered.startswith(("data:", "stdin:", "\\\\", "//")):
        return "unsupported_platform"
    if "\x00" in text:
        return "input_unavailable"
    return None


def _read_local_file(raw_path: str | None, *, limit: int) -> bytes:
    if type(raw_path) is not str:
        fail("input_unavailable")
    special = _is_explicit_remote_or_special(raw_path)
    if special is not None:
        fail(special)
    path = Path(raw_path)
    try:
        initial = os.lstat(path)
    except (OSError, ValueError):
        fail("input_unavailable")
    if stat.S_ISLNK(initial.st_mode) or not stat.S_ISREG(initial.st_mode):
        fail("input_unavailable")
    # Windows reparse points include symlinks and remote/device forms. A
    # regular-file mode bit alone is not enough to make those safe.
    if getattr(initial, "st_file_attributes", 0) & 0x400:
        fail("unsupported_platform")

    flags = os.O_RDONLY
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except (OSError, ValueError):
        fail("input_unavailable")
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            fail("input_unavailable")
        if getattr(opened, "st_file_attributes", 0) & 0x400:
            fail("unsupported_platform")
        # On POSIX, O_NOFOLLOW plus this identity check closes the ordinary
        # symlink/replacement race. Windows receives the opened-handle type
        # check and retains its documented caller-owned mount policy.
        if hasattr(initial, "st_ino") and hasattr(opened, "st_ino"):
            if initial.st_ino != opened.st_ino or initial.st_dev != opened.st_dev:
                fail("input_unavailable")
        if opened.st_size > limit:
            fail("input_too_large")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(64 * 1024, limit + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > limit:
                fail("input_too_large")
        return b"".join(chunks)
    except MudraValidationError:
        raise
    except (OSError, ValueError):
        fail("input_unavailable")
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def _parse_frames(data: bytes, *, stabilize: bool) -> tuple[Frame, ...]:
    if not stabilize:
        return (parse_frame(data),)
    # A one-frame --stabilize input proves that one observation cannot become
    # stable. A batch is fully parsed before any session state advances, so a
    # malformed late frame has no partial-success path.
    document = parse_json_bytes(data, limit=MAX_BATCH_BYTES)
    if isinstance(document, dict) and "frames" not in document:
        if len(data) > MAX_FRAME_BYTES:
            fail("input_too_large")
        return (parse_frame(document),)
    return parse_batch(document).frames


def _party(value: str | None, default: InteractionParty) -> InteractionParty:
    selected = default.value if value is None else value
    if type(selected) is not str:
        fail("invalid_shape")
    try:
        return InteractionParty(selected)
    except (ValueError, TypeError):
        fail("invalid_shape")


def _reason_code(state: RecognitionState, uncertainties: Sequence[str]) -> str | None:
    if state is RecognitionState.STABLE:
        return None
    present = set(uncertainties)
    for code in _REASON_PRECEDENCE:
        if code in present:
            return code
    if state is RecognitionState.CANDIDATE:
        return "insufficient_frames"
    return "unsupported_pattern"


def _recognition_report(session: RecognitionSession) -> bytes:
    recognition = session.current
    result = {
        "schema_version": SCHEMA_VERSION,
        "recognition": recognition.payload(),
        "reason_code": _reason_code(recognition.state, recognition.uncertainties),
    }
    return json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _run_recognize(args: argparse.Namespace) -> bytes:
    if args.emit_event and not args.stabilize:
        raise _UsageError
    if not args.emit_event and (args.consent or args.confirm):
        raise _UsageError
    data = _read_local_file(args.input_path, limit=MAX_BATCH_BYTES if args.stabilize else MAX_FRAME_BYTES)
    frames = _parse_frames(data, stabilize=args.stabilize)

    # Parse and validate all event-only options before checking either consent
    # flag, matching the contract's precedence rule.
    sender = _party(args.sender, InteractionParty.HUMAN)
    recipient = _party(args.recipient, InteractionParty.AGENT)
    conversation_id = require_canonical_uuid(args.conversation_id, nullable=True)
    project_id = require_canonical_uuid(args.project_id, nullable=True)
    session = RecognitionSession(
        frames[0].stream_id,
        conversation_id=conversation_id,
        project_id=project_id,
    )
    for frame in frames:
        session.observe(frame)
    final_time = frames[-1].monotonic_ms

    if args.emit_event:
        if args.consent is not True:
            fail("consent_required")
        if args.confirm is not True:
            fail("confirmation_required")
        session.confirm(True, True, final_time)
        event = session.emit_event(
            sender=sender,
            recipient=recipient,
            now_ms=final_time,
            occurred_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        )
        return event.to_bytes()
    return _recognition_report(session)


def _run_validate_event(args: argparse.Namespace) -> bytes:
    data = _read_local_file(args.input_path, limit=MAX_EVENT_BYTES)
    parse_event(data)
    return b'{"schema_version":"2.0.0","valid":true}'


def _validate_namespace(args: argparse.Namespace) -> None:
    if args.command is None:
        args.command = "recognize"
    if args.command == "validate-event":
        if args.input_path is None or args.stabilize or args.emit_event or args.consent or args.confirm:
            raise _UsageError
        if any(value is not None for value in (args.sender, args.recipient, args.conversation_id, args.project_id)):
            raise _UsageError
    elif args.input_path is None:
        raise _UsageError


def _help_bytes(parser: argparse.ArgumentParser) -> bytes:
    return parser.format_help().encode("utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
        if args.help:
            return _emit_success(_help_bytes(parser).rstrip(b"\n"))
        if args.version:
            meaningful = [
                args.command,
                args.input_path,
                args.stabilize,
                args.emit_event,
                args.consent,
                args.confirm,
                args.sender,
                args.recipient,
                args.conversation_id,
                args.project_id,
            ]
            if any(value not in (None, False) for value in meaningful):
                raise _UsageError
            return _emit_success(_package_version().encode("ascii"))
        _validate_namespace(args)
        output = _run_validate_event(args) if args.command == "validate-event" else _run_recognize(args)
        return _emit_success(output)
    except _UsageError:
        _emit_error("invalid_shape")
        return EXIT_USAGE
    except MudraValidationError as error:
        _emit_error(error.code)
        if error.code in {"consent_required", "confirmation_required", "stale_confirmation"}:
            return EXIT_DENIED
        if error.code in {"input_unavailable", "unsupported_platform", "internal_error"}:
            return EXIT_IO
        return EXIT_USAGE
    except KeyboardInterrupt:
        _emit_error("internal_error")
        return EXIT_INTERRUPTED
    except _OutputError:
        return EXIT_IO
    except Exception:
        # No implementation detail, path, raw input or traceback may cross the
        # command boundary.
        _emit_error("internal_error")
        return EXIT_IO


__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main())
