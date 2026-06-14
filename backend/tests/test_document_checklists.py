"""The document-checklist catalog (app.document_checklists) is static reference
data, so it's tested directly — every planning entity type must have a non-empty
required + beneficial list, and every row must carry a name, a form/source, and a
why. No DB, no engine: pure shape + completeness assertions over the frozen table.
"""

from __future__ import annotations

import pytest

from app.document_checklists import (
    DOCUMENT_CHECKLISTS,
    ENTITY_TYPES,
    checklist_for,
    entity_types,
)

# The planning-capable entity types (everything in the catalog). `not_sure` is a
# UX affordance with no checklist and is deliberately excluded.
PLANNING_ENTITY_TYPES = sorted(DOCUMENT_CHECKLISTS)


def test_expected_entity_types_present() -> None:
    # The six planning entity types the product promises (not_sure is UX-only).
    assert set(DOCUMENT_CHECKLISTS) == {
        "individual",
        "sole_prop",
        "partnership",
        "s_corp",
        "c_corp",
        "multi_entity",
    }


@pytest.mark.parametrize("entity_type", PLANNING_ENTITY_TYPES)
def test_each_entity_has_nonempty_required_and_beneficial(entity_type: str) -> None:
    entry = DOCUMENT_CHECKLISTS[entity_type]
    assert entry["required"], f"{entity_type} has no required docs"
    assert entry["beneficial"], f"{entity_type} has no beneficial docs"


@pytest.mark.parametrize("entity_type", PLANNING_ENTITY_TYPES)
def test_every_doc_has_name_source_and_why(entity_type: str) -> None:
    entry = DOCUMENT_CHECKLISTS[entity_type]
    for bucket in ("required", "beneficial"):
        for doc in entry[bucket]:
            assert doc.name.strip(), f"{entity_type}/{bucket}: empty name"
            assert doc.form_or_source.strip(), f"{entity_type}/{bucket}: {doc.name} missing form_or_source"
            assert doc.why.strip(), f"{entity_type}/{bucket}: {doc.name} missing why"
            # The `why` is meant to be a real plain-English sentence, not a stub.
            assert len(doc.why) >= 20, f"{entity_type}/{bucket}: {doc.name} why is too short"


@pytest.mark.parametrize("entity_type", PLANNING_ENTITY_TYPES)
def test_checklist_for_serializes_to_api_shape(entity_type: str) -> None:
    out = checklist_for(entity_type)
    assert out["entity_type"] == entity_type
    assert isinstance(out["label"], str) and out["label"]
    for bucket in ("required", "beneficial"):
        rows = out[bucket]
        assert isinstance(rows, list) and rows
        for row in rows:
            # Serialized rows are plain dicts with exactly the documented keys.
            assert set(row) == {"name", "form_or_source", "why"}


def test_checklist_for_rejects_unknown_entity_type() -> None:
    with pytest.raises(KeyError):
        checklist_for("partnership_llc_typo")


def test_not_sure_is_a_picker_option_but_has_no_checklist() -> None:
    keys = {e.key for e in ENTITY_TYPES}
    assert "not_sure" in keys
    assert "not_sure" not in DOCUMENT_CHECKLISTS
    with pytest.raises(KeyError):
        checklist_for("not_sure")


def test_entity_types_helper_matches_catalog_plus_not_sure() -> None:
    listed = entity_types()
    # Every listed type is a dict with the picker contract.
    for item in listed:
        assert set(item) == {"key", "label", "description"}
        assert item["label"] and item["description"]
    keys = {item["key"] for item in listed}
    # Every planning entity type in the catalog is offered in the picker.
    assert set(DOCUMENT_CHECKLISTS).issubset(keys)
