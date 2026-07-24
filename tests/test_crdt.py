"""Stable public-surface tests for the Yrs-backed collaborative document."""

from __future__ import annotations

import json

import pytest

from dhad import Dhad
from dhad.crdt import CrdtDocument


def test_single_site_editing_behaves_like_a_python_string() -> None:
    document = CrdtDocument("editor")
    document.local_insert(0, "مرحبا")
    document.local_insert(5, " بالعالم")
    assert document.text == "مرحبا بالعالم"
    document.local_delete(0, 6)
    document.replace(0, 3, "لل")
    assert document.text == "للعالم"


def test_scalar_bounds_are_enforced() -> None:
    document = CrdtDocument("editor")
    document.local_insert(0, "اب")
    with pytest.raises(IndexError):
        document.local_insert(5, "خطأ")
    with pytest.raises(IndexError):
        document.local_delete(1, 5)
    with pytest.raises(ValueError):
        CrdtDocument("")


def test_duplicate_binary_updates_are_idempotent() -> None:
    source = CrdtDocument("source")
    target = CrdtDocument("target")
    update = source.local_insert(0, "نص")
    assert target.apply(update) is True
    assert target.apply(update) is False
    assert target.text == "نص"


def test_json_wrapper_roundtrips_portable_yjs_state() -> None:
    original = CrdtDocument("site")
    original.local_insert(0, "نص للحفظ")
    original.local_delete(2, 1)
    restored = CrdtDocument.from_json(original.to_json())
    assert restored.text == original.text
    restored.local_insert(0, "أ")
    assert restored.text.startswith("أ")


def test_legacy_rga_snapshot_migrates_visible_text_once() -> None:
    legacy = json.dumps(
        {
            "site": "legacy",
            "counter": 3,
            "nodes": [
                {"id": [1, "legacy"], "parent": [0, ""], "value": "ن", "deleted": False},
                {"id": [2, "legacy"], "parent": [1, "legacy"], "value": "ص", "deleted": True},
                {"id": [3, "legacy"], "parent": [2, "legacy"], "value": "ي", "deleted": False},
            ],
            "pending": [],
        },
        ensure_ascii=False,
    )
    migrated = CrdtDocument.from_json(legacy)
    assert migrated.text == "ني"
    assert migrated.to_json() != legacy


def test_legacy_snapshot_with_unresolved_operations_is_not_silently_migrated() -> None:
    legacy = json.dumps(
        {"site": "legacy", "counter": 0, "nodes": [], "pending": [{"kind": "insert"}]}
    )
    with pytest.raises(ValueError, match="pending"):
        CrdtDocument.from_json(legacy)


def test_crdt_text_feeds_incremental_checking() -> None:
    checker = Dhad()
    document = CrdtDocument("editor")
    document.local_insert(0, "ذهبت الى المدرسه صباحا. انا سعيد جدا.")
    session = checker.session(document.text)
    assert "HAMZA_ILA" in {match.rule_id for match in session.matches}

    index = document.text.index("المدرسه")
    document.replace(index, index + len("المدرسه"), "المكتبه")
    session.update(document.text)
    assert session.matches == checker.check(document.text)
