"""Sweep-line interval indexes for overlap resolution — V2 Phase 2.

Replaces the historical quadratic ``any(candidate.overlaps(existing) ...)``
scans in the check pipeline and in :func:`dhad.match.dedupe` with
``O(log n)`` queries. Two shapes cover every call site:

* :class:`FrozenSpanIndex` — built once over a *static* set of possibly
  overlapping spans (one engine layer filtering against everything accepted
  by earlier layers). Sorted starts plus a prefix-maximum of ends answer
  "does [start, end) overlap anything?" with a single bisection.
* :class:`DisjointSpanIndex` — a *growing* AVL tree of guaranteed-disjoint
  spans (the winner set inside ``dedupe``). Predecessor/successor lookup and
  balanced insertion are both worst-case ``O(log n)``.

Overlap semantics are identical to :meth:`dhad.match.Match.overlaps`
(half-open, strict): ``a.start < b.end and b.start < a.end``. Equivalence
with the quadratic reference is enforced bit-for-bit by
``tests/test_spans.py``.
"""

from __future__ import annotations

from bisect import bisect_left
from typing import Iterable, Protocol


class HasSpan(Protocol):
    offset: int

    @property
    def end(self) -> int: ...


class FrozenSpanIndex:
    """Immutable overlap oracle over possibly-overlapping spans."""

    __slots__ = ("_starts", "_max_ends")

    def __init__(self, spans: Iterable[tuple[int, int]]) -> None:
        ordered = sorted(spans)
        self._starts = [start for start, _end in ordered]
        self._max_ends: list[int] = []
        running = 0
        for index, (_start, end) in enumerate(ordered):
            running = end if index == 0 else max(running, end)
            self._max_ends.append(running)

    @classmethod
    def from_matches(cls, matches: Iterable[HasSpan]) -> "FrozenSpanIndex":
        return cls((match.offset, match.end) for match in matches)

    def __len__(self) -> int:
        return len(self._starts)

    def overlaps(self, start: int, end: int) -> bool:
        """True when [start, end) strictly overlaps any stored span.

        Candidates are the stored spans whose start precedes ``end``; among
        those, an overlap exists iff the maximum stored end exceeds
        ``start`` — exactly the prefix maximum at the bisection point.
        """

        index = bisect_left(self._starts, end)
        return index > 0 and self._max_ends[index - 1] > start

    def overlaps_match(self, match: HasSpan) -> bool:
        return self.overlaps(match.offset, match.end)


class _SpanNode:
    __slots__ = ("start", "end", "height", "left", "right")

    def __init__(self, start: int, end: int) -> None:
        self.start = start
        self.end = end
        self.height = 1
        self.left: _SpanNode | None = None
        self.right: _SpanNode | None = None


def _height(node: _SpanNode | None) -> int:
    return node.height if node is not None else 0


def _refresh(node: _SpanNode) -> None:
    node.height = 1 + max(_height(node.left), _height(node.right))


def _rotate_left(root: _SpanNode) -> _SpanNode:
    pivot = root.right
    if pivot is None:  # pragma: no cover - guarded by the AVL balance factor
        raise RuntimeError("AVL left rotation requires a right child")
    root.right = pivot.left
    pivot.left = root
    _refresh(root)
    _refresh(pivot)
    return pivot


def _rotate_right(root: _SpanNode) -> _SpanNode:
    pivot = root.left
    if pivot is None:  # pragma: no cover - guarded by the AVL balance factor
        raise RuntimeError("AVL right rotation requires a left child")
    root.left = pivot.right
    pivot.right = root
    _refresh(root)
    _refresh(pivot)
    return pivot


def _insert(root: _SpanNode | None, start: int, end: int) -> _SpanNode:
    if root is None:
        return _SpanNode(start, end)
    if start < root.start:
        root.left = _insert(root.left, start, end)
    elif start > root.start:
        root.right = _insert(root.right, start, end)
    else:
        raise ValueError(f"A span already starts at offset {start}")

    _refresh(root)
    balance = _height(root.left) - _height(root.right)
    if balance > 1:
        if root.left is not None and start > root.left.start:
            root.left = _rotate_left(root.left)
        return _rotate_right(root)
    if balance < -1:
        if root.right is not None and start < root.right.start:
            root.right = _rotate_right(root.right)
        return _rotate_left(root)
    return root


class DisjointSpanIndex:
    """Growing AVL overlap index for a set of disjoint half-open spans.

    Both lookup and insertion are worst-case ``O(log n)``. The former list
    representation used logarithmic bisection but paid ``O(n)`` to shift
    elements on every insertion, making adversarial deduplication quadratic.
    """

    __slots__ = ("_root", "_size")

    def __init__(self) -> None:
        self._root: _SpanNode | None = None
        self._size = 0

    def __len__(self) -> int:
        return self._size

    @property
    def depth(self) -> int:
        """Current tree depth, exposed for complexity-regression tests."""

        return _height(self._root)

    def overlaps(self, start: int, end: int) -> bool:
        """True when [start, end) strictly overlaps any stored span.

        Stored spans are disjoint and sorted, so only the immediate left
        neighbour (which might reach over ``start``) and the immediate right
        neighbour (which might begin before ``end``) can possibly collide.
        """

        node = self._root
        predecessor: _SpanNode | None = None
        successor: _SpanNode | None = None
        while node is not None:
            if node.start <= start:
                predecessor = node
                node = node.right
            else:
                successor = node
                node = node.left
        return bool(
            (predecessor is not None and predecessor.end > start)
            or (successor is not None and successor.start < end)
        )

    def add(self, start: int, end: int) -> None:
        """Insert a span known not to overlap the stored set."""

        self._root = _insert(self._root, start, end)
        self._size += 1


def filter_non_overlapping(candidates: Iterable[HasSpan], accepted: Iterable[HasSpan]) -> list:
    """Return candidates that do not overlap any accepted match.

    Drop-in sweep-line replacement for the historical pattern::

        [c for c in candidates if not any(c.overlaps(a) for a in accepted)]

    Candidates are *not* filtered against each other, mirroring the original
    per-layer semantics of ``Dhad.check`` exactly.
    """

    index = FrozenSpanIndex.from_matches(accepted)
    if not len(index):
        return list(candidates)
    return [candidate for candidate in candidates if not index.overlaps_match(candidate)]
