from __future__ import annotations

import copy
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
from typing import Any

import pytest

from mudra_interact_core import (
    A2A_BINDING,
    A2AClient,
    A2AInteropError,
    A2A_PROTOCOL_RELEASE,
    A2A_PROTOCOL_VERSION,
    A2A_SPEC_EDITION,
    AuthenticatedPrincipal,
    InMemoryReplayStore,
    Message,
    parse_message,
)


ROOT = Path(__file__).resolve().parents[1]
HUMAN_ID = "33333333-3333-4333-8333-333333333333"
HUMAN_AGENT_ID = "44444444-4444-4444-8444-444444444444"
AGENT_ALPHA_ID = "55555555-5555-4555-8555-555555555555"
AGENT_BETA_ID = "66666666-6666-4666-8666-666666666666"
CONVERSATION_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
NOW = "2026-10-08T13:00:30.000000Z"


def _base_request(*, agent_sender: bool = False) -> dict[str, Any]:
    filename = "agent-agent.json" if agent_sender else "human-agent.json"
    transcript = json.loads(
        (ROOT / "src/mudra_interact_core/examples/language" / filename).read_text(encoding="utf-8")
    )
    result = copy.deepcopy(transcript["messages"][0])
    result["message_id"] = (
        "30000000-0000-4000-8000-000000000001"
        if agent_sender else "20000000-0000-4000-8000-000000000001"
    )
    result["conversation_id"] = CONVERSATION_ID
    result["created_at"] = "2026-10-08T13:00:00.000000Z"
    result["expires_at"] = "2026-10-08T13:10:00.000000Z"
    return result


def _reply(request: Message, act: str, payload: dict[str, Any], *, stale: bool = False) -> dict[str, Any]:
    response = request.payload()
    response.update({
        "message_id": "70000000-0000-4000-8000-000000000001",
        "sender": {"participant_id": request.recipient.participant_id, "kind": "agent"},
        "recipient": {"participant_id": request.sender.participant_id, "kind": request.sender.kind},
        "reply_to": request.message_id,
        "created_at": "2026-10-08T12:00:00.000000Z" if stale else NOW,
        "expires_at": "2026-10-08T12:10:00.000000Z" if stale else "2026-10-08T13:10:30.000000Z",
        "act": act,
        "intent": {
            "name": request.intent.name,
            "version": request.intent.version,
            "payload": payload,
        },
        "provenance": {
            "mode": "agent", "adapter_id": "org.mayayai.test_peer",
            "adapter_version": "1.0.0", "interpretation_score": None,
            "human_reviewed": False,
        },
    })
    return response


class _IndependentA2APeer(BaseHTTPRequestHandler):
    """A separate HTTP A2A JSON-RPC peer; it does not call the Mudra adapter."""

    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length).decode("utf-8"))
        self.server.requests.append({  # type: ignore[attr-defined]
            "rpc": request,
            "version": self.headers.get("A2A-Version"),
            "content_type": self.headers.get("Content-Type"),
            "authorization": self.headers.get("Authorization"),
        })
        rpc_id = request.get("id")
        if getattr(self.server, "rpc_error_code", None) is not None:  # type: ignore[attr-defined]
            error = {"code": self.server.rpc_error_code, "message": "synthetic secret peer detail"}  # type: ignore[attr-defined]
            if getattr(self.server, "rpc_error_data", None) is not None:  # type: ignore[attr-defined]
                error["data"] = self.server.rpc_error_data  # type: ignore[attr-defined]
            if getattr(self.server, "rpc_error_extra", None) is not None:  # type: ignore[attr-defined]
                error["unexpected"] = self.server.rpc_error_extra  # type: ignore[attr-defined]
            raw = json.dumps({
                "jsonrpc": "2.0", "id": rpc_id,
                "error": error,
            }).encode("utf-8")
            if getattr(self.server, "response_content_type", "application/json") != "application/json":  # type: ignore[attr-defined]
                raw = b""
            self.send_response(200)
            self.send_header("Content-Type", getattr(self.server, "response_content_type", "application/json"))  # type: ignore[attr-defined]
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if request.get("method") == "SendMessage":
            message = request["params"]["message"]
            mudra_wire = message["parts"][0]["data"]["mudra_message"]
            inbound = parse_message(mudra_wire)
            if inbound.act == "request":
                response_message = _reply(
                    inbound, "proposal", {"summary": "Independent peer plan", "steps": [
                        {"step_id": 1, "description": "Review the synthetic brief."},
                    ]},
                    stale=getattr(self.server, "stale_reply", False),  # type: ignore[attr-defined]
                )
                state = "TASK_STATE_INPUT_REQUIRED"
            elif inbound.act == "accept":
                # Injected failure signal: no model/provider is invoked by this peer.
                response_message = _reply(inbound, "error", {"code": "provider_unavailable"})
                state = "TASK_STATE_FAILED"
            else:
                response_message = _reply(inbound, "acknowledge", {})
                state = "TASK_STATE_INPUT_REQUIRED"
            peer_task = {
                "id": "peer-task-001", "contextId": (
                    "foreign-context-001" if getattr(self.server, "foreign_context", False)  # type: ignore[attr-defined]
                    else "peer-context-001"
                ),
                "status": {"state": state, "message": {
                    "messageId": "peer-message-001", "role": "ROLE_AGENT",
                    "taskId": "peer-task-001", "contextId": "peer-context-001",
                    "parts": [{
                        "data": {"mudra_message": response_message},
                        "mediaType": "application/json",
                    }],
                }},
            }
            self.server.provider_calls += 0  # type: ignore[attr-defined]
            result = {"task": peer_task}
        elif request.get("method") == "CancelTask":
            result = {"task": {
                "id": request["params"]["id"], "contextId": "peer-context-001",
                "status": {"state": "TASK_STATE_CANCELED"},
            }}
        else:
            result = None
        raw = json.dumps({"jsonrpc": "2.0", "id": rpc_id, "result": result}).encode("utf-8")
        if getattr(self.server, "response_content_type", "application/json") != "application/json":  # type: ignore[attr-defined]
            raw = b""
        self.send_response(200)
        self.send_header("Content-Type", getattr(self.server, "response_content_type", "application/json"))  # type: ignore[attr-defined]
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, _format: str, *_args: Any) -> None:
        return


@pytest.fixture
def peer() -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _IndependentA2APeer)
    server.requests = []  # type: ignore[attr-defined]
    server.provider_calls = 0  # type: ignore[attr-defined]
    server.stale_reply = False  # type: ignore[attr-defined]
    server.rpc_error_code = None  # type: ignore[attr-defined]
    server.rpc_error_data = None  # type: ignore[attr-defined]
    server.rpc_error_extra = None  # type: ignore[attr-defined]
    server.response_content_type = "application/json"  # type: ignore[attr-defined]
    server.foreign_context = False  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_port}/rpc"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _client(endpoint: str, *, replay_store: InMemoryReplayStore | None = None,
            token_provider=None, remote_agent_id: str = HUMAN_AGENT_ID,
            remote_tenant: str | None = None) -> A2AClient:
    return A2AClient(
        endpoint,
        remote_agent_id=remote_agent_id,
        replay_store=replay_store or InMemoryReplayStore(),
        clock_utc=lambda: NOW,
        remote_tenant=remote_tenant,
        token_provider=token_provider,
    )


def _principal(*, agent: bool = False, tenant: str = "tenant-1") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        participant_id=AGENT_ALPHA_ID if agent else HUMAN_ID,
        kind="agent" if agent else "human",
        tenant_id=tenant,
    )


def _accept_message(*, agent_sender: bool = False) -> dict[str, Any]:
    message = _base_request(agent_sender=agent_sender)
    message.update({
        "message_id": "30000000-0000-4000-8000-000000000003"
        if agent_sender else "20000000-0000-4000-8000-000000000005",
        "reply_to": "30000000-0000-4000-8000-000000000002"
        if agent_sender else "20000000-0000-4000-8000-000000000004",
        "created_at": NOW,
        "expires_at": "2026-10-08T13:10:30.000000Z",
        "act": "accept",
        "intent": {"name": "org.mayayai.creative.plan", "version": "1.0.0", "payload": {}},
    })
    return message


@pytest.mark.acceptance("L50")
def test_live_a2a_jsonrpc_round_trip_binds_human_agent_path_and_pinned_version(peer) -> None:
    server, endpoint = peer
    client = _client(endpoint, token_provider=lambda: "synthetic-test-token")
    request = parse_message(_base_request())

    result = client.send(request, principal=_principal())

    assert (A2A_SPEC_EDITION, A2A_PROTOCOL_RELEASE, A2A_PROTOCOL_VERSION) == ("1.0.1", "1.0.0", "1.0")
    assert A2A_BINDING == "JSON-RPC over HTTP(S)"
    assert result.message is not None
    assert result.message.act == "proposal"
    assert result.message.sender.participant_id == HUMAN_AGENT_ID
    assert result.task is not None
    assert result.task.task_id == "peer-task-001"
    assert result.task.context_id == "peer-context-001"
    recorded = server.requests[0]  # type: ignore[attr-defined]
    assert recorded["version"] == "1.0"
    assert recorded["content_type"] == "application/json"
    assert recorded["authorization"] == "Bearer synthetic-test-token"
    assert recorded["rpc"]["method"] == "SendMessage"
    assert "tenant" not in recorded["rpc"]["params"]
    outer = recorded["rpc"]["params"]["message"]
    assert recorded["rpc"]["id"] != request.message_id
    assert outer["role"] == "ROLE_USER"  # transport direction, not Mudra identity
    assert outer["messageId"] != request.message_id
    assert outer["parts"] == [{
        "data": {"mudra_message": request.payload()},
        "mediaType": "application/json",
    }]
    assert "taskId" not in outer and "contextId" not in outer


@pytest.mark.acceptance("L51")
@pytest.mark.parametrize("agent_sender", [False, True], ids=["human_to_agent", "agent_to_agent"])
def test_live_a2a_supports_client_to_agent_roles_without_confusing_transport_role(peer, agent_sender: bool) -> None:
    server, endpoint = peer
    client = _client(endpoint, remote_agent_id=AGENT_BETA_ID if agent_sender else HUMAN_AGENT_ID)
    request = _base_request(agent_sender=agent_sender)
    principal = _principal(agent=agent_sender)

    result = client.send(request, principal=principal)

    assert result.message is not None and result.message.sender.kind == "agent"
    assert result.message.recipient.kind == principal.kind
    sent = server.requests[0]["rpc"]["params"]["message"]  # type: ignore[attr-defined]
    assert sent["role"] == "ROLE_USER"
    assert sent["parts"][0]["data"]["mudra_message"]["sender"]["kind"] == principal.kind
    assert server.provider_calls == 0  # type: ignore[attr-defined]


@pytest.mark.acceptance("L51")
def test_task_continuation_replay_refusal_and_explicit_cancellation_are_separate(peer) -> None:
    server, endpoint = peer
    client = _client(endpoint, remote_tenant="remote-interface-tenant")
    principal = _principal()
    first = parse_message(_base_request())
    started = client.send(first, principal=principal)
    assert started.task is not None

    accepted = parse_message(_accept_message())
    outcome = client.send(accepted, principal=principal, task=started.task)
    assert outcome.message is not None
    assert outcome.message.act == "error"
    assert outcome.message.intent.payload["code"] == "provider_unavailable"
    continuation = server.requests[1]["rpc"]  # type: ignore[attr-defined]
    outer = continuation["params"]["message"]
    assert continuation["params"]["tenant"] == "remote-interface-tenant"
    assert outer["taskId"] == started.task.task_id
    assert outer["contextId"] == started.task.context_id
    assert server.provider_calls == 0  # type: ignore[attr-defined]

    # A fresh task demonstrates cancellation only after an explicit cancel() call.
    other_client = _client(endpoint, remote_tenant="remote-interface-tenant")
    second = copy.deepcopy(_base_request())
    second["message_id"] = "80000000-0000-4000-8000-000000000001"
    opened = other_client.send(second, principal=principal)
    assert opened.task is not None
    cancelled = other_client.cancel(opened.task, principal=principal)
    assert cancelled.state == "TASK_STATE_CANCELED"
    assert server.requests[-1]["rpc"]["method"] == "CancelTask"  # type: ignore[attr-defined]
    assert server.requests[-1]["rpc"]["params"]["tenant"] == "remote-interface-tenant"  # type: ignore[attr-defined]
    assert server.provider_calls == 0  # type: ignore[attr-defined]


@pytest.mark.acceptance("L51")
def test_decline_is_sent_as_data_and_does_not_cancel_task(peer) -> None:
    server, endpoint = peer
    client = _client(endpoint)
    principal = _principal()
    request = parse_message(_base_request())
    started = client.send(request, principal=principal)
    assert started.task is not None

    decline = copy.deepcopy(_accept_message())
    decline.update({
        "message_id": "90000000-0000-4000-8000-000000000001",
        "reply_to": "20000000-0000-4000-8000-000000000004",
        "act": "decline",
        "intent": {"name": "org.mayayai.creative.plan", "version": "1.0.0", "payload": {"reason": "needs_revision"}},
    })
    result = client.send(decline, principal=principal, task=started.task)

    assert result.message is not None and result.message.act == "acknowledge"
    assert server.requests[-1]["rpc"]["method"] == "SendMessage"  # type: ignore[attr-defined]
    assert server.provider_calls == 0  # type: ignore[attr-defined]


@pytest.mark.acceptance("L51")
def test_stale_outbound_and_stale_remote_messages_are_rejected(peer) -> None:
    server, endpoint = peer
    client = _client(endpoint)
    stale = _base_request()
    stale["created_at"] = "2026-10-08T12:00:00.000000Z"
    stale["expires_at"] = "2026-10-08T12:05:00.000000Z"
    with pytest.raises(A2AInteropError) as caught:
        client.send(stale, principal=_principal())
    assert caught.value.code == "expired_message"
    assert server.requests == []  # type: ignore[attr-defined]

    server.stale_reply = True  # type: ignore[attr-defined]
    with pytest.raises(A2AInteropError) as caught:
        client.send(_base_request(), principal=_principal())
    assert caught.value.code == "expired_message"


@pytest.mark.acceptance("L51")
def test_human_to_human_remains_schema_only(peer) -> None:
    server, endpoint = peer
    wire = _base_request()
    wire["recipient"] = {"participant_id": HUMAN_AGENT_ID, "kind": "human"}
    wire["sender"] = {"participant_id": HUMAN_ID, "kind": "human"}
    message = parse_message(wire)
    assert message.recipient.kind == "human"
    client = _client(endpoint)
    with pytest.raises(A2AInteropError) as caught:
        client.send(message, principal=_principal())
    assert caught.value.code == "scope_mismatch"
    assert server.requests == []  # type: ignore[attr-defined]


@pytest.mark.acceptance("L51")
def test_replay_identity_tenant_and_task_scope_fail_before_wrong_operation(peer) -> None:
    server, endpoint = peer
    store = InMemoryReplayStore()
    client = _client(endpoint, replay_store=store)
    request = _base_request()
    principal = _principal()
    client.send(request, principal=principal)
    with pytest.raises(A2AInteropError) as caught:
        client.send(request, principal=principal)
    assert caught.value.code == "replayed_message"
    assert len(server.requests) == 1  # type: ignore[attr-defined]

    wrong_sender = _base_request()
    wrong_sender["message_id"] = "80000000-0000-4000-8000-000000000002"
    with pytest.raises(A2AInteropError) as caught:
        client.send(wrong_sender, principal=_principal(agent=True))
    assert caught.value.code == "permission_denied"
    assert len(server.requests) == 1  # type: ignore[attr-defined]

    started = client.send(
        {**_base_request(), "message_id": "80000000-0000-4000-8000-000000000003"},
        principal=principal,
    )
    assert started.task is not None
    other_remote_tenant = _client(endpoint, remote_tenant="another-remote-interface")
    with pytest.raises(A2AInteropError) as caught:
        other_remote_tenant.send(
            {**_base_request(), "message_id": "80000000-0000-4000-8000-000000000004"},
            principal=principal,
            task=started.task,
        )
    assert caught.value.code == "scope_mismatch"
    assert len(server.requests) == 2  # type: ignore[attr-defined]
    with pytest.raises(A2AInteropError) as caught:
        client.cancel(started.task, principal=_principal(tenant="other-tenant"))
    assert caught.value.code == "scope_mismatch"
    assert len(server.requests) == 2  # type: ignore[attr-defined]


@pytest.mark.acceptance("L52")
def test_endpoint_and_peer_errors_fail_closed_without_leaking_remote_text(peer) -> None:
    server, endpoint = peer
    store = InMemoryReplayStore()
    for invalid in (
        "http://example.com/rpc", "https://user:secret@example.com/rpc",
        "https://example.com/rpc?token=secret", "https://example.com/rpc#fragment",
    ):
        with pytest.raises(A2AInteropError) as caught:
            A2AClient(invalid, remote_agent_id=HUMAN_AGENT_ID, replay_store=store, clock_utc=lambda: NOW)
        assert caught.value.code == "invalid_endpoint"

    for invalid_tenant in ("", "x" * 257, "remote\ntenant"):
        with pytest.raises(A2AInteropError) as caught:
            A2AClient(
                endpoint, remote_agent_id=HUMAN_AGENT_ID, remote_tenant=invalid_tenant,
                replay_store=store, clock_utc=lambda: NOW,
            )
        assert caught.value.code == "invalid_configuration"

    assert endpoint.startswith("http://127.0.0.1:")
    server.rpc_error_code = -32603  # type: ignore[attr-defined]
    with pytest.raises(A2AInteropError) as caught:
        _client(endpoint).send(_base_request(), principal=_principal())
    assert caught.value.code == "peer_error"
    assert "synthetic secret peer detail" not in str(caught.value)
    assert "synthetic secret peer detail" not in repr(caught.value)

    server.rpc_error_code = -32009  # A2A VersionNotSupportedError.  # type: ignore[attr-defined]
    server.rpc_error_data = [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "VERSION_NOT_SUPPORTED"}]  # type: ignore[attr-defined]
    with pytest.raises(A2AInteropError) as caught:
        _client(endpoint).send(_base_request(), principal=_principal())
    assert caught.value.code == "unsupported_version"

    server.rpc_error_code = -32603  # type: ignore[attr-defined]
    server.rpc_error_data = None  # type: ignore[attr-defined]
    server.rpc_error_extra = "unsupported"  # type: ignore[attr-defined]
    with pytest.raises(A2AInteropError) as caught:
        _client(endpoint).send(_base_request(), principal=_principal())
    assert caught.value.code == "invalid_response"

    server.rpc_error_code = None  # type: ignore[attr-defined]
    server.rpc_error_extra = None  # type: ignore[attr-defined]
    server.response_content_type = "application/a2a+json"  # type: ignore[attr-defined]
    with pytest.raises(A2AInteropError) as caught:
        _client(endpoint).send(_base_request(), principal=_principal())
    assert caught.value.code == "invalid_response"


@pytest.mark.acceptance("L52")
def test_parsing_does_not_send_and_mudra_accept_never_calls_provider(peer) -> None:
    server, endpoint = peer
    request = parse_message(_base_request())
    assert isinstance(request, Message)
    assert server.requests == []  # type: ignore[attr-defined]
    assert server.provider_calls == 0  # type: ignore[attr-defined]

    client = _client(endpoint)
    started = client.send(request, principal=_principal())
    assert started.task is not None
    accepted = parse_message(_accept_message())
    client.send(accepted, principal=_principal(), task=started.task)
    assert server.provider_calls == 0  # type: ignore[attr-defined]
    assert [row["rpc"]["method"] for row in server.requests] == ["SendMessage", "SendMessage"]  # type: ignore[attr-defined]


@pytest.mark.acceptance("L52")
def test_invalid_shapes_and_inconsistent_peer_context_are_rejected(peer) -> None:
    server, endpoint = peer
    client = _client(endpoint)
    malformed = _base_request()
    malformed["recipient"]["participant_id"] = AGENT_BETA_ID
    with pytest.raises(A2AInteropError) as caught:
        client.send(malformed, principal=_principal())
    assert caught.value.code == "scope_mismatch"
    assert server.requests == []  # type: ignore[attr-defined]

    server.foreign_context = True  # type: ignore[attr-defined]
    with pytest.raises(A2AInteropError) as caught:
        client.send(_base_request(), principal=_principal())
    assert caught.value.code == "scope_mismatch"

    with pytest.raises(A2AInteropError) as caught:
        AuthenticatedPrincipal(HUMAN_ID, [], "tenant-1")  # type: ignore[arg-type]
    assert caught.value.code == "invalid_configuration"
