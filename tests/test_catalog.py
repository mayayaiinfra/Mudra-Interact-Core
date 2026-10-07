from __future__ import annotations

import copy

import pytest

from mudra_interact_core.catalog import (
    CATALOG_IDS,
    load_catalog,
    lookup,
    validate_catalog_payload,
    validate_label_pack,
)
from mudra_interact_core.errors import MudraValidationError


@pytest.mark.acceptance("E56")
def test_catalogue_contains_exact_neutral_rule_records() -> None:
    catalog = load_catalog()
    assert set(catalog) == CATALOG_IDS
    assert len(catalog) == 4
    assert {entry["contact_pattern"] for entry in catalog.values()} == {"I", "M", "R", "M+R"}
    assert all(entry["provenance"]["status"] == "specification_source" for entry in catalog.values())
    assert all(entry["provenance"]["content_license"] == "Apache-2.0" for entry in catalog.values())


@pytest.mark.acceptance("E57")
@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: value.update(catalog_version="1.0.0"),
        lambda value: value["entries"].pop(),
        lambda value: value["entries"].append(copy.deepcopy(value["entries"][0])),
        lambda value: value["entries"][0].update(unknown="x"),
        lambda value: value["entries"][0].update(gesture_id="unknown"),
        lambda value: value["entries"][0].update(provenance={"status": "approved"}),
    ],
)
def test_malformed_catalogue_is_rejected_without_drop_or_overwrite(mutator) -> None:
    value = {"catalog_version": "2.0.0", "entries": list(load_catalog().values())}
    mutator(value)
    with pytest.raises(MudraValidationError, match="catalog_invalid"):
        validate_catalog_payload(value)


@pytest.mark.acceptance("E58")
def test_lookup_returns_detached_data() -> None:
    first = lookup("contact_thumb_index")
    assert first is not None
    first["limitations"].append("caller mutation")
    first["provenance"]["reference"] = "tampered"
    second = lookup("contact_thumb_index")
    assert second is not None
    assert "caller mutation" not in second["limitations"]
    assert second["provenance"]["reference"] != "tampered"
    assert lookup("unknown") is None


@pytest.mark.acceptance("E59")
def test_historical_names_are_documented_as_disabled_aliases() -> None:
    documentation = open("docs/CATALOG_REVIEW.md", encoding="utf-8").read()
    for alias in ("Gyan", "Chin", "Shunya", "Prithvi", "Apana"):
        assert alias in documentation
    assert "not enabled" in documentation
    assert all(alias.lower() not in load_catalog() for alias in ("gyan_mudra", "shunya_mudra", "prithvi_mudra"))


@pytest.mark.acceptance("E60")
def test_label_pack_requires_review_shape_and_does_not_approve_it() -> None:
    with pytest.raises(MudraValidationError, match="catalog_invalid"):
        validate_label_pack({"pack_version": "1.0.0", "entries": [{"label": "alias"}]})
    reviewed_shape = {
        "pack_version": "1.0.0",
        "entries": [
            {
                "gesture_id": "contact_thumb_index",
                "label": "example",
                "reviewer": "human-reviewer-id",
                "evidence_reference": "review-ticket-1",
                "rights": "documented",
                "language_scope": "en/example",
                "prohibited_claims": "no efficacy claim",
                "withdrawal": "contact owner",
            }
        ],
    }
    result = validate_label_pack(reviewed_shape)
    assert result == reviewed_shape


@pytest.mark.acceptance("E61")
def test_neutral_catalogue_copy_has_no_efficacy_or_authority_claims() -> None:
    forbidden = ("heals", "cures", "diagnoses", "therapeutic", "religious authority", "medical")
    for entry in load_catalog().values():
        text = " ".join([entry["display_name"], *entry["limitations"]]).lower()
        assert not any(word in text for word in forbidden)

