"""Yrs-backed collaborative text with the Yjs binary update protocol.

The implementation delegates CRDT integration, state vectors, update merging,
and tombstone garbage collection to :mod:`pycrdt`, the Python binding backed by
the Rust ``yrs`` implementation.  Dhad therefore exchanges the same compact
binary updates as Yjs instead of maintaining a bespoke character RGA.

Public editor offsets are Python Unicode-scalar offsets.  ``pycrdt`` exposes
UTF-8 byte offsets, so the small conversion helpers at this boundary keep the
rest of Dhad's diagnostic-offset contract unchanged.
"""

from __future__ import annotations

import base64
import binascii
import json
import threading
from collections.abc import Iterable

from pycrdt import Assoc, Doc, StickyIndex, Text, merge_updates

_TEXT_ROOT = "text"
_PERSISTENCE_FORMAT = "dhad-yjs-update-v1"


def merge_binary_updates(*updates: bytes) -> bytes:
    """Merge Yjs updates without materializing a document."""

    if not updates:
        return b"\x00\x00"
    if any(not isinstance(update, bytes) for update in updates):
        raise TypeError("Yjs updates must be bytes")
    try:
        return merge_updates(*updates)
    except (RuntimeError, ValueError) as exc:
        raise ValueError("Invalid Yjs update") from exc


class CrdtDocument:
    """A garbage-collecting Yrs/Yjs text replica.

    Local editing methods return one binary Yjs update suitable for direct
    encryption and transport.  Remote updates are commutative, idempotent, and
    may be delivered in any order by the synchronization backend.
    """

    def __init__(self, site_id: str) -> None:
        if not isinstance(site_id, str) or not site_id:
            raise ValueError("site_id must be a non-empty string")
        self._site_id = site_id
        self._lock = threading.RLock()
        # Yjs client ids are replica-session identities, not user/site names.
        # Let Yrs generate a fresh random id so two tabs with the same site
        # label can never write on the same logical clock.
        self._doc = Doc(skip_gc=False)
        self._doc[_TEXT_ROOT] = Text()
        self._text: Text = self._doc[_TEXT_ROOT]

    @property
    def site_id(self) -> str:
        return self._site_id

    @property
    def client_id(self) -> int:
        return self._doc.client_id

    @property
    def garbage_collection_enabled(self) -> bool:
        """Yrs is configured to compact deleted content during transactions."""

        return True

    @property
    def text(self) -> str:
        with self._lock:
            return str(self._text)

    def __len__(self) -> int:
        return len(self.text)

    @property
    def state_vector(self) -> bytes:
        """Return the compact Yjs state vector for delta negotiation."""

        with self._lock:
            return self._doc.get_state()

    @property
    def version_vector(self) -> bytes:
        """Backward-named alias for callers migrating to binary state vectors."""

        return self.state_vector

    def encode_update(self, state_vector: bytes | None = None) -> bytes:
        """Encode the full state or only changes missing from ``state_vector``."""

        if state_vector is not None and not isinstance(state_vector, bytes):
            raise TypeError("state_vector must be bytes")
        with self._lock:
            try:
                return self._doc.get_update(state_vector)
            except (RuntimeError, ValueError) as exc:
                raise ValueError("Invalid Yjs state vector") from exc

    def _scalar_to_native(self, index: int) -> int:
        value = str(self._text)
        if index < 0 or index > len(value):
            raise IndexError(index)
        return len(value[:index].encode("utf-8"))

    def _native_to_scalar(self, index: int) -> int:
        encoded = str(self._text).encode("utf-8")
        if index < 0 or index > len(encoded):
            raise IndexError(index)
        try:
            return len(encoded[:index].decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise ValueError("Yrs returned a non-character text anchor") from exc

    def _edit(self, operation) -> bytes:
        before = self._doc.get_state()
        operation()
        return self._doc.get_update(before)

    def local_insert(self, index: int, text: str) -> bytes:
        """Insert text before a Unicode-scalar offset and return its Yjs update."""

        if not isinstance(text, str):
            raise TypeError("text must be a string")
        with self._lock:
            native_index = self._scalar_to_native(index)
            if not text:
                return self._doc.get_update(self._doc.get_state())
            return self._edit(lambda: self._text.insert(native_index, text))

    def local_delete(self, index: int, length: int = 1) -> bytes:
        """Delete a scalar range and return its compact Yjs update."""

        if length < 0:
            raise ValueError("length must be non-negative")
        with self._lock:
            end = index + length
            start_native = self._scalar_to_native(index)
            end_native = self._scalar_to_native(end)
            if length == 0:
                return self._doc.get_update(self._doc.get_state())
            return self._edit(lambda: self._text.__delitem__(slice(start_native, end_native)))

    def replace(self, start: int, end: int, text: str) -> bytes:
        """Replace ``[start, end)`` as one mergeable Yjs delta."""

        if end < start:
            raise ValueError("end must not precede start")
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        with self._lock:
            start_native = self._scalar_to_native(start)
            end_native = self._scalar_to_native(end)

            def mutate() -> None:
                if end_native > start_native:
                    del self._text[start_native:end_native]
                if text:
                    self._text.insert(start_native, text)

            return self._edit(mutate)

    def apply(self, update: bytes) -> bool:
        """Apply one Yjs update and return whether it changed the state vector."""

        if not isinstance(update, bytes):
            raise TypeError("Yjs update must be bytes")
        with self._lock:
            before = self._doc.get_state()
            try:
                self._doc.apply_update(update)
            except (RuntimeError, ValueError) as exc:
                raise ValueError("Invalid Yjs update") from exc
            return self._doc.get_state() != before

    def apply_all(self, updates: Iterable[bytes]) -> None:
        for update in updates:
            self.apply(update)

    def anchor_at(self, index: int) -> bytes:
        """Return a portable Yjs sticky anchor for a scalar offset."""

        with self._lock:
            native_index = self._scalar_to_native(index)
            return self._text.sticky_index(native_index, Assoc.BEFORE).encode()

    def resolve_anchor(self, anchor: bytes) -> int:
        """Resolve a sticky anchor to its current Unicode-scalar offset."""

        if not isinstance(anchor, bytes):
            raise TypeError("anchor must be bytes")
        with self._lock:
            try:
                sticky = StickyIndex.decode(anchor, self._text)
                return self._native_to_scalar(sticky.get_index())
            except (RuntimeError, ValueError) as exc:
                raise ValueError("Invalid Yjs sticky anchor") from exc

    # Compatibility names for the pre-vMAX anchor surface.  Values are now
    # standard encoded Yjs sticky indexes rather than custom operation tuples.
    id_at = anchor_at
    index_of = resolve_anchor

    def to_bytes(self) -> bytes:
        """Serialize a portable full-state Yjs update."""

        return self.encode_update()

    @classmethod
    def from_bytes(cls, site_id: str, update: bytes) -> "CrdtDocument":
        replica = cls(site_id)
        replica.apply(update)
        return replica

    def to_json(self) -> str:
        """Serialize a versioned base64 wrapper for JSON-only persistence."""

        return json.dumps(
            {
                "format": _PERSISTENCE_FORMAT,
                "site": self._site_id,
                "update": base64.b64encode(self.to_bytes()).decode("ascii"),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, payload: str) -> "CrdtDocument":
        try:
            data = json.loads(payload)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Invalid CRDT persistence payload") from exc
        if not isinstance(data, dict):
            raise ValueError("Invalid CRDT persistence payload")
        if data.get("format") == _PERSISTENCE_FORMAT:
            try:
                update = base64.b64decode(data["update"], validate=True)
                return cls.from_bytes(str(data["site"]), update)
            except (KeyError, TypeError, binascii.Error, ValueError) as exc:
                raise ValueError("Invalid CRDT persistence payload") from exc
        if "nodes" in data and "site" in data:
            pending = data.get("pending", [])
            if not isinstance(pending, list) or pending:
                raise ValueError("Legacy CRDT snapshot has unresolved pending operations")
            nodes = data["nodes"]
            if not isinstance(nodes, list):
                raise ValueError("Invalid legacy CRDT nodes")
            visible: list[str] = []
            for node in nodes:
                if not isinstance(node, dict):
                    raise ValueError("Invalid legacy CRDT node")
                value = node.get("value")
                deleted = node.get("deleted")
                if not isinstance(value, str) or len(value) != 1 or not isinstance(deleted, bool):
                    raise ValueError("Invalid legacy CRDT node")
                if not deleted:
                    visible.append(value)
            migrated = cls(str(data["site"]))
            if visible:
                migrated.local_insert(0, "".join(visible))
            return migrated
        raise ValueError("Unsupported CRDT persistence format")
