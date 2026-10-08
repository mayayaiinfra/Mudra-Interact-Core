"""Apache-2.0 Mudra Interact Core."""

from .errors import MudraValidationError
from .catalog import load_catalog, lookup
from .coordinates import convert_landmarks, to_cartesian
from .frame import Frame, FrameBatch, Landmark, parse_batch, parse_frame
from .protocol import (
    InteractionParty,
    MudraEvent,
    PrivacyMode,
    Recognition,
    RecognitionState,
    parse_event,
)
from .validation import InteractionConfig
from .session import RecognitionSession
from .recognition import LandmarkRuleRecognizer, RecognitionStabilizer, extract_contact_features
from .language import (
    LanguageValidationError,
    Message,
    check_freshness,
    parse_message,
    render_message,
    validate_transcript,
)
from .a2a import (
    A2AClient,
    A2A_BINDING,
    A2AInteropError,
    A2A_PROTOCOL_RELEASE,
    A2A_PROTOCOL_VERSION,
    A2A_SPEC_EDITION,
    A2ASendResult,
    A2ATaskRef,
    AuthenticatedPrincipal,
    InMemoryReplayStore,
)

__all__ = [
    "InteractionParty",
    "InteractionConfig",
    "load_catalog",
    "lookup",
    "convert_landmarks",
    "Frame",
    "FrameBatch",
    "Landmark",
    "MudraEvent",
    "MudraValidationError",
    "parse_batch",
    "parse_event",
    "parse_frame",
    "to_cartesian",
    "PrivacyMode",
    "Recognition",
    "RecognitionState",
    "RecognitionSession",
    "LandmarkRuleRecognizer",
    "RecognitionStabilizer",
    "extract_contact_features",
    "LanguageValidationError",
    "Message",
    "parse_message",
    "check_freshness",
    "validate_transcript",
    "render_message",
    "A2AClient",
    "A2A_BINDING",
    "A2AInteropError",
    "A2A_PROTOCOL_RELEASE",
    "A2A_PROTOCOL_VERSION",
    "A2A_SPEC_EDITION",
    "A2ASendResult",
    "A2ATaskRef",
    "AuthenticatedPrincipal",
    "InMemoryReplayStore",
]
