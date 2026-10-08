"""Strict A2A 1.0 JSON-RPC transport for Mudra messages.

The adapter is deliberately separate from the offline language SDK. It sends
one validated Mudra payload as one A2A DataPart and never calls a model, tool,
or provider. The host supplies identity, time, credentials, tenant scope, and a
durable replay store.
"""

from __future__ import annotations

from dataclasses import dataclass
import http.client
import hashlib
import json
import math
import re
import socket
import ssl
import threading
from typing import Any, Callable, Protocol
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from .language import LanguageValidationError, Message, check_freshness, parse_message
from .validation import parse_json_bytes


A2A_SPEC_EDITION = "1.0.1"
A2A_PROTOCOL_RELEASE = "1.0.0"
A2A_PROTOCOL_VERSION = "1.0"
A2A_BINDING = "JSON-RPC over HTTP(S)"
A2A_MEDIA_TYPE = "application/json"
MUDRA_DATA_MEDIA_TYPE = "application/json"
MAX_A2A_RESPONSE_BYTES = 131_072
_A2A_ID_MAX = 256
_TENANT_MAX = 256
_TOKEN_MAX = 8_192
_TASK_STATES = frozenset({
    "TASK_STATE_SUBMITTED", "TASK_STATE_WORKING", "TASK_STATE_INPUT_REQUIRED",
    "TASK_STATE_AUTH_REQUIRED", "TASK_STATE_COMPLETED", "TASK_STATE_FAILED",
    "TASK_STATE_CANCELED", "TASK_STATE_REJECTED",
})
_TERMINAL_STATES = frozenset({
    "TASK_STATE_COMPLETED", "TASK_STATE_FAILED", "TASK_STATE_CANCELED", "TASK_STATE_REJECTED",
})
_ERROR_CODES = frozenset({
    "invalid_endpoint", "invalid_configuration", "invalid_message", "expired_message",
    "permission_denied", "scope_mismatch", "replayed_message", "replay_store_unavailable",
    "transport_error", "peer_error", "unsupported_version", "invalid_response",
})


class A2AInteropError(ValueError):
    """A fixed, non-sensitive error from the A2A transport boundary."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code if type(code) is str and code in _ERROR_CODES else "invalid_response"
        super().__init__(self.code)

    def __str__(self) -> str:
        return self.code

    def __repr__(self) -> str:
        return f"A2AInteropError({self.code!r})"


def _fail(code: str) -> None:
    raise A2AInteropError(code)


def _canonical_uuid(value: Any) -> bool:
    if type(value) is not str or len(value) != 36 or value.lower() != value:
        return False
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError):
        return False
    return str(parsed) == value and parsed.variant == "specified in RFC 4122"


def _bounded_id(value: Any) -> bool:
    return (
        type(value) is str and 1 <= len(value) <= _A2A_ID_MAX
        and not any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)
    )


def _tenant(value: Any) -> bool:
    return (
        type(value) is str and 1 <= len(value) <= _TENANT_MAX
        and not any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)
    )


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    """Identity asserted by the host after its own authentication checks."""

    participant_id: str
    kind: str
    tenant_id: str

    def __post_init__(self) -> None:
        if (
            not _canonical_uuid(self.participant_id) or type(self.kind) is not str
            or self.kind not in {"human", "agent"} or not _tenant(self.tenant_id)
        ):
            _fail("invalid_configuration")


class ReplayStore(Protocol):
    """Host-owned atomic replay store; production hosts should use durable storage."""

    def claim(self, replay_key: str) -> bool:
        """Atomically claim a key once. Return False when it was already claimed."""


class InMemoryReplayStore:
    """Process-local replay guard for tests and single-process demonstrations only."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._claimed: set[str] = set()

    def claim(self, replay_key: str) -> bool:
        if type(replay_key) is not str or not re.fullmatch(r"[0-9a-f]{64}", replay_key):
            return False
        with self._lock:
            if replay_key in self._claimed:
                return False
            self._claimed.add(replay_key)
            return True


@dataclass(frozen=True, slots=True)
class A2ATaskRef:
    """A server-issued task handle bound to one conversation and host scope."""

    task_id: str
    context_id: str
    state: str
    endpoint: str
    remote_agent_id: str
    remote_tenant: str | None
    principal_id: str
    principal_kind: str
    tenant_id: str
    mudra_conversation_id: str


@dataclass(frozen=True, slots=True)
class A2ASendResult:
    """Validated response data; absence of a reply is represented as None."""

    task: A2ATaskRef | None
    message: Message | None
    task_state: str | None


def _endpoint_parts(endpoint: Any) -> tuple[str, str, int | None, str]:
    if type(endpoint) is not str or not (1 <= len(endpoint) <= 2_048):
        _fail("invalid_endpoint")
    try:
        parsed = urlsplit(endpoint)
        port = parsed.port
    except ValueError:
        _fail("invalid_endpoint")
    if (
        parsed.scheme not in {"https", "http"} or not parsed.hostname
        or parsed.username is not None or parsed.password is not None
        or parsed.query or parsed.fragment or "\\" in parsed.path
        or any(ord(char) < 0x20 for char in endpoint)
    ):
        _fail("invalid_endpoint")
    host = parsed.hostname.lower()
    if parsed.scheme == "http" and host not in {"localhost", "127.0.0.1", "::1"}:
        _fail("invalid_endpoint")
    path = parsed.path or "/"
    if not path.startswith("/"):
        _fail("invalid_endpoint")
    return parsed.scheme, host, port, path


class A2AClient:
    """Synchronous A2A JSON-RPC client with explicit host security dependencies.

    This client uses the pinned A2A v1.0 wire contract directly with the Python
    standard library. It does not import or require the A2A SDK. No retry or
    redirect is followed; a transport outcome that is uncertain consumes the
    Mudra message ID in the replay store and must be reconciled by the host.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        remote_agent_id: str,
        replay_store: ReplayStore,
        clock_utc: Callable[[], str],
        remote_tenant: str | None = None,
        token_provider: Callable[[], str | None] | None = None,
        timeout_seconds: int | float = 10,
        max_response_bytes: int = MAX_A2A_RESPONSE_BYTES,
    ) -> None:
        scheme, host, port, path = _endpoint_parts(endpoint)
        if not _canonical_uuid(remote_agent_id):
            _fail("invalid_configuration")
        if remote_tenant is not None and not _tenant(remote_tenant):
            _fail("invalid_configuration")
        if not callable(getattr(replay_store, "claim", None)) or not callable(clock_utc):
            _fail("invalid_configuration")
        if token_provider is not None and not callable(token_provider):
            _fail("invalid_configuration")
        if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or not 1 <= timeout_seconds <= 60:
            _fail("invalid_configuration")
        if type(max_response_bytes) is not int or not 1_024 <= max_response_bytes <= MAX_A2A_RESPONSE_BYTES:
            _fail("invalid_configuration")
        self.endpoint = endpoint
        self.remote_agent_id = remote_agent_id
        self.remote_tenant = remote_tenant
        self._scheme = scheme
        self._host = host
        self._port = port
        self._path = path
        self._replay_store = replay_store
        self._clock_utc = clock_utc
        self._token_provider = token_provider
        self._timeout = float(timeout_seconds)
        self._max_response_bytes = max_response_bytes

    def send(self, message: Message | bytes | dict[str, Any], *, principal: AuthenticatedPrincipal,
             task: A2ATaskRef | None = None) -> A2ASendResult:
        """Send one Mudra message through A2A after scope, freshness and replay checks."""
        if type(principal) is not AuthenticatedPrincipal:
            _fail("permission_denied")
        try:
            parsed = message if type(message) is Message else parse_message(message)  # type: ignore[arg-type]
        except LanguageValidationError:
            _fail("invalid_message")
        self._check_outbound(parsed, principal, task)
        self._check_fresh(parsed)
        replay_key = _replay_key(
            principal.participant_id, principal.tenant_id, self.remote_agent_id, parsed.message_id,
        )
        try:
            claimed = self._replay_store.claim(replay_key)
        except Exception:
            _fail("replay_store_unavailable")
        if claimed is not True:
            _fail("replayed_message")

        rpc_request_id = str(uuid4())
        params: dict[str, Any] = {
            "message": _encode_a2a_message(parsed, task),
        }
        if self.remote_tenant is not None:
            # A2A tenant identifies the remote AgentInterface routing target.
            # The authenticated host tenant remains local scope and is never
            # forwarded implicitly.
            params["tenant"] = self.remote_tenant
        rpc_request = {
            "jsonrpc": "2.0",
            "id": rpc_request_id,
            "method": "SendMessage",
            "params": params,
        }
        response = self._rpc(rpc_request)
        result = _rpc_result(response, rpc_request_id)
        if set(result) == {"task"}:
            task_object = _validate_task_object(result["task"])
            if task is not None and (
                task_object["id"] != task.task_id or task_object["contextId"] != task.context_id
            ):
                _fail("scope_mismatch")
            status = task_object["status"]
            task_ref = self._task_ref(task_object, parsed, principal)
            remote_message = None
            if "message" in status:
                remote_message = _decode_a2a_message(
                    status["message"], request=parsed, principal=principal,
                    remote_agent_id=self.remote_agent_id, clock_utc=self._clock_utc,
                    expected_task=task_object,
                )
            return A2ASendResult(task_ref, remote_message, status["state"])
        if set(result) == {"message"}:
            remote_message = _decode_a2a_message(
                result["message"], request=parsed, principal=principal,
                remote_agent_id=self.remote_agent_id, clock_utc=self._clock_utc,
            )
            return A2ASendResult(None, remote_message, None)
        _fail("invalid_response")

    def cancel(self, task: A2ATaskRef, *, principal: AuthenticatedPrincipal) -> A2ATaskRef:
        """Explicitly request A2A task cancellation; decline messages never call this."""
        self._check_task_scope(task, principal)
        if task.state in _TERMINAL_STATES:
            _fail("scope_mismatch")
        request_id = str(uuid4())
        params: dict[str, Any] = {"id": task.task_id}
        if self.remote_tenant is not None:
            params["tenant"] = self.remote_tenant
        response = self._rpc({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "CancelTask",
            "params": params,
        })
        result = _rpc_result(response, request_id)
        if set(result) != {"task"}:
            _fail("invalid_response")
        task_object = _validate_task_object(result["task"])
        if task_object["id"] != task.task_id or task_object["contextId"] != task.context_id:
            _fail("scope_mismatch")
        state = task_object["status"]["state"]
        if state != "TASK_STATE_CANCELED":
            _fail("invalid_response")
        return A2ATaskRef(
            task_id=task.task_id,
            context_id=task.context_id,
            state=state,
            endpoint=task.endpoint,
            remote_agent_id=task.remote_agent_id,
            remote_tenant=task.remote_tenant,
            principal_id=task.principal_id,
            principal_kind=task.principal_kind,
            tenant_id=task.tenant_id,
            mudra_conversation_id=task.mudra_conversation_id,
        )

    def _check_outbound(self, message: Message, principal: AuthenticatedPrincipal,
                        task: A2ATaskRef | None) -> None:
        if (
            message.sender.participant_id != principal.participant_id
            or message.sender.kind != principal.kind
        ):
            _fail("permission_denied")
        if message.recipient.participant_id != self.remote_agent_id or message.recipient.kind != "agent":
            _fail("scope_mismatch")
        if task is not None:
            self._check_task_scope(task, principal)
            if task.mudra_conversation_id != message.conversation_id or task.state in _TERMINAL_STATES:
                _fail("scope_mismatch")

    def _check_task_scope(self, task: A2ATaskRef, principal: AuthenticatedPrincipal) -> None:
        if type(task) is not A2ATaskRef or type(principal) is not AuthenticatedPrincipal:
            _fail("scope_mismatch")
        if (
            not _bounded_id(task.task_id) or not _bounded_id(task.context_id)
            or task.endpoint != self.endpoint or task.remote_agent_id != self.remote_agent_id
            or task.remote_tenant != self.remote_tenant
            or task.principal_id != principal.participant_id or task.principal_kind != principal.kind
            or task.tenant_id != principal.tenant_id
            or not _canonical_uuid(task.mudra_conversation_id)
            or type(task.state) is not str or task.state not in _TASK_STATES
        ):
            _fail("scope_mismatch")

    def _check_fresh(self, message: Message) -> None:
        try:
            now = self._clock_utc()
            check_freshness(message, now)
        except LanguageValidationError as exc:
            _fail("expired_message" if exc.code == "expired_message" else "invalid_message")
        except Exception:
            _fail("invalid_configuration")

    def _task_ref(self, task: dict[str, Any], message: Message,
                  principal: AuthenticatedPrincipal) -> A2ATaskRef:
        return A2ATaskRef(
            task_id=task["id"],
            context_id=task["contextId"],
            state=task["status"]["state"],
            endpoint=self.endpoint,
            remote_agent_id=self.remote_agent_id,
            remote_tenant=self.remote_tenant,
            principal_id=principal.participant_id,
            principal_kind=principal.kind,
            tenant_id=principal.tenant_id,
            mudra_conversation_id=message.conversation_id,
        )

    def _rpc(self, request: dict[str, Any]) -> dict[str, Any]:
        try:
            body = json.dumps(request, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":"), allow_nan=False).encode("utf-8", errors="strict")
            headers = {
                "Content-Type": A2A_MEDIA_TYPE,
                "Accept": A2A_MEDIA_TYPE,
                "A2A-Version": A2A_PROTOCOL_VERSION,
            }
            if self._token_provider is not None:
                try:
                    token = self._token_provider()
                except Exception:
                    _fail("invalid_configuration")
                if token is not None:
                    if (
                        type(token) is not str or not (1 <= len(token) <= _TOKEN_MAX)
                        or any(ord(char) < 0x21 or ord(char) > 0x7E for char in token)
                    ):
                        _fail("invalid_configuration")
                    headers["Authorization"] = f"Bearer {token}"
            if self._scheme == "https":
                connection: http.client.HTTPConnection = http.client.HTTPSConnection(
                    self._host, self._port, timeout=self._timeout, context=ssl.create_default_context(),
                )
            else:
                connection = http.client.HTTPConnection(self._host, self._port, timeout=self._timeout)
            try:
                connection.request("POST", self._path, body=body, headers=headers)
                response = connection.getresponse()
                if response.status != 200:
                    if response.status in {401, 403}:
                        _fail("permission_denied")
                    _fail("transport_error")
                media_type = response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
                if media_type != "application/json":
                    _fail("invalid_response")
                if response.getheader("Content-Encoding", "identity").lower() not in {"", "identity"}:
                    _fail("invalid_response")
                response_body = response.read(self._max_response_bytes + 1)
                if len(response_body) > self._max_response_bytes:
                    _fail("invalid_response")
            finally:
                connection.close()
        except A2AInteropError:
            raise
        except (OSError, http.client.HTTPException, socket.timeout, ssl.SSLError, UnicodeError, ValueError):
            _fail("transport_error")
        try:
            value = parse_json_bytes(
                response_body, limit=self._max_response_bytes, max_depth=16,
                max_string_scalars=self._max_response_bytes,
            )
        except Exception:
            _fail("invalid_response")
        if type(value) is not dict:
            _fail("invalid_response")
        return value


def _replay_key(principal_id: str, tenant_id: str, agent_id: str, message_id: str) -> str:
    material = json.dumps(
        [principal_id, tenant_id, agent_id, message_id], ensure_ascii=True, separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(material).hexdigest()


def _encode_a2a_message(message: Message, task: A2ATaskRef | None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "messageId": str(uuid4()),
        "role": "ROLE_USER",  # A2A client-to-server role, not a Mudra human/agent claim.
        "parts": [{
            "data": {"mudra_message": message.payload()},
            "mediaType": MUDRA_DATA_MEDIA_TYPE,
        }],
    }
    if task is not None:
        result["taskId"] = task.task_id
        result["contextId"] = task.context_id
    return result


def _exact_object(value: Any, required: set[str], optional: set[str] | None = None) -> dict[str, Any]:
    if type(value) is not dict or not required.issubset(value):
        _fail("invalid_response")
    if set(value) - required - (optional or set()):
        _fail("invalid_response")
    return value


def _rpc_result(response: dict[str, Any], request_id: str) -> dict[str, Any]:
    if response.get("jsonrpc") != "2.0" or response.get("id") != request_id:
        _fail("invalid_response")
    if set(response) == {"jsonrpc", "id", "error"}:
        error = response["error"]
        if (
            type(error) is not dict
            or set(error) not in ({"code", "message"}, {"code", "message", "data"})
            or type(error.get("code")) is not int
            or type(error.get("message")) is not str
            or not (1 <= len(error["message"]) <= 1_024)
            or (
                "data" in error
                and (
                    type(error["data"]) is not list
                    or len(error["data"]) > 32
                    or any(
                        type(detail) is not dict
                        or type(detail.get("@type")) is not str
                        or not detail["@type"]
                        for detail in error["data"]
                    )
                )
            )
        ):
            _fail("invalid_response")
        if error.get("code") == -32009:
            _fail("unsupported_version")
        _fail("peer_error")
    if set(response) != {"jsonrpc", "id", "result"} or type(response["result"]) is not dict:
        _fail("invalid_response")
    return response["result"]


def _validate_task_object(value: Any) -> dict[str, Any]:
    task = _exact_object(
        value, {"id", "contextId", "status"},
        {"artifacts", "history", "metadata", "tenant", "referenceTaskIds"},
    )
    if not _bounded_id(task["id"]) or not _bounded_id(task["contextId"]):
        _fail("invalid_response")
    status = _exact_object(task["status"], {"state"}, {"message", "timestamp"})
    if type(status["state"]) is not str or status["state"] not in _TASK_STATES:
        _fail("invalid_response")
    return task


def _decode_a2a_message(value: Any, *, request: Message, principal: AuthenticatedPrincipal,
                        remote_agent_id: str, clock_utc: Callable[[], str],
                        expected_task: dict[str, Any] | None = None) -> Message:
    outer = _exact_object(
        value, {"messageId", "role", "parts"},
        {"contextId", "taskId", "extensions", "metadata", "referenceTaskIds"},
    )
    if not _bounded_id(outer["messageId"]) or outer["role"] != "ROLE_AGENT":
        _fail("invalid_response")
    if "extensions" in outer and outer["extensions"] not in ([], {}):
        _fail("unsupported_version")
    parts = outer["parts"]
    if type(parts) is not list or len(parts) != 1:
        _fail("invalid_response")
    part = _exact_object(parts[0], {"data", "mediaType"})
    if part["mediaType"] != MUDRA_DATA_MEDIA_TYPE or type(part["data"]) is not dict:
        _fail("invalid_response")
    data = _exact_object(part["data"], {"mudra_message"})
    try:
        parsed = parse_message(data["mudra_message"])
    except LanguageValidationError:
        _fail("invalid_response")
    if (
        parsed.sender.participant_id != remote_agent_id or parsed.sender.kind != "agent"
        or parsed.recipient.participant_id != principal.participant_id
        or parsed.recipient.kind != principal.kind
        or parsed.conversation_id != request.conversation_id
        or parsed.reply_to != request.message_id
        or parsed.intent.name != request.intent.name or parsed.intent.version != request.intent.version
    ):
        _fail("scope_mismatch")
    try:
        check_freshness(parsed, clock_utc())
    except LanguageValidationError as exc:
        _fail("expired_message" if exc.code == "expired_message" else "invalid_response")
    except Exception:
        _fail("invalid_configuration")
    if outer.get("taskId") is not None and not _bounded_id(outer["taskId"]):
        _fail("invalid_response")
    if outer.get("contextId") is not None and not _bounded_id(outer["contextId"]):
        _fail("invalid_response")
    if expected_task is not None and (
        outer.get("taskId") != expected_task["id"]
        or outer.get("contextId") != expected_task["contextId"]
    ):
        _fail("scope_mismatch")
    return parsed


__all__ = [
    "A2AClient", "A2AInteropError", "A2ASendResult", "A2ATaskRef",
    "AuthenticatedPrincipal", "InMemoryReplayStore", "ReplayStore",
    "A2A_SPEC_EDITION", "A2A_PROTOCOL_RELEASE", "A2A_PROTOCOL_VERSION", "A2A_BINDING",
]
