"""vMAX Phase 4 acceptance tests for the Yrs/Yjs document core."""

from __future__ import annotations

import random

import pytest

import dhad.crdt as crdt

CrdtDocument = crdt.CrdtDocument


def test_state_vectors_produce_compact_missing_updates() -> None:
    alice = CrdtDocument("alice")
    bob = CrdtDocument("bob")

    first = alice.local_insert(0, "مرحبا")
    assert isinstance(first, bytes)
    bob.apply(first)

    bob_state = bob.state_vector
    second = alice.local_insert(len(alice), " بالعالم")
    missing = alice.encode_update(bob_state)

    assert missing == second
    assert len(missing) < len(alice.encode_update())
    bob.apply(missing)
    assert bob.text == alice.text == "مرحبا بالعالم"


def test_same_site_label_still_creates_unique_yjs_client_ids() -> None:
    first = CrdtDocument("editor")
    second = CrdtDocument("editor")
    assert first.client_id != second.client_id


def test_yrs_updates_converge_under_random_delivery_and_duplicates() -> None:
    rng = random.Random(20260722)
    replicas = [CrdtDocument(f"site-{index}") for index in range(3)]
    seed = replicas[0].local_insert(0, "نص البداية")
    for replica in replicas[1:]:
        replica.apply(seed)

    updates: list[bytes] = []
    for _ in range(40):
        replica = rng.choice(replicas)
        if len(replica) and rng.random() < 0.4:
            position = rng.randrange(len(replica))
            updates.append(replica.local_delete(position, 1))
        else:
            position = rng.randrange(len(replica) + 1)
            updates.append(replica.local_insert(position, rng.choice("ابتثجحخدذرزسشصض ")))

    merged = crdt.merge_binary_updates(*updates)
    for replica in replicas:
        deliveries = updates + rng.sample(updates, 10)
        rng.shuffle(deliveries)
        replica.apply_all(deliveries)
        replica.apply(merged)

    assert len({replica.text for replica in replicas}) == 1


def test_sticky_anchor_survives_concurrent_prefix_insert() -> None:
    left = CrdtDocument("left")
    right = CrdtDocument("right")
    right.apply(left.local_insert(0, "خطأ هنا"))

    anchor = left.anchor_at(4)
    left.apply(right.local_insert(0, "مقدمة: "))

    assert left.text[left.resolve_anchor(anchor)] == "ه"


def test_binary_persistence_roundtrip_keeps_gc_enabled() -> None:
    original = CrdtDocument("author")
    original.local_insert(0, "نص قديم")
    original.local_delete(3, 4)

    restored = CrdtDocument.from_bytes("restored", original.to_bytes())

    assert restored.text == original.text
    assert restored.garbage_collection_enabled is True


def test_invalid_binary_update_is_rejected() -> None:
    with pytest.raises(ValueError, match="Yjs update"):
        CrdtDocument("site").apply(b"not-a-yjs-update")
