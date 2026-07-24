"""vMAX encrypted synchronization with Redis fanout and durable recovery.

The FastAPI process is a blind router. Binary Yjs updates and snapshots arrive
as opaque authenticated ciphertext; the server validates only a versioned
frame header and never parses, logs, or decrypts document content. Redis
Pub/Sub supplies cross-worker live fanout while Redis Streams journal the same
blobs behind durable resume cursors. A separately stored encrypted snapshot
lets clients recover after Stream trimming.

Every socket owns a bounded outgoing mailbox and writer task. Publishing only
enqueues, so a stalled network peer cannot block a room; a full mailbox evicts
that peer with an application close code. Connection-local token buckets,
strict byte limits, origin checks, optional API-key authentication, paged
recovery, and reconnecting Pub/Sub listeners complete the resilience boundary.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import struct
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

try:
    from redis.asyncio import Redis
except ImportError:  # pragma: no cover - exercised by minimal non-server installs
    Redis = Any  # type: ignore[misc,assignment]

# Binary application frames.  The kind byte is routing metadata; every update
# and snapshot payload following it is opaque authenticated ciphertext.
FRAME_UPDATE = 1
FRAME_SNAPSHOT = 2
FRAME_KEY_ANNOUNCEMENT = 3
_FRAME_KINDS = frozenset({FRAME_UPDATE, FRAME_SNAPSHOT, FRAME_KEY_ANNOUNCEMENT})
_CLIENT_MAGIC = b"DHC4"
_SERVER_MAGIC = b"DHS4"
_CLIENT_HEADER = struct.Struct("!4sB")
_SERVER_HEADER = struct.Struct("!4sBHH")


@dataclass(frozen=True, slots=True)
class ClientFrame:
    kind: int
    payload: bytes


@dataclass(frozen=True, slots=True)
class ServerFrame:
    kind: int
    cursor: str
    sender: str
    payload: bytes


def pack_client_frame(frame: ClientFrame) -> bytes:
    if frame.kind not in _FRAME_KINDS:
        raise ValueError("Unsupported sync frame kind")
    if not isinstance(frame.payload, bytes):
        raise TypeError("Frame payload must be bytes")
    return _CLIENT_HEADER.pack(_CLIENT_MAGIC, frame.kind) + frame.payload


def unpack_client_frame(data: bytes) -> ClientFrame:
    if not isinstance(data, bytes) or len(data) < _CLIENT_HEADER.size:
        raise ValueError("Invalid client sync frame")
    magic, kind = _CLIENT_HEADER.unpack_from(data)
    if magic != _CLIENT_MAGIC or kind not in _FRAME_KINDS:
        raise ValueError("Invalid client sync frame")
    return ClientFrame(kind=kind, payload=data[_CLIENT_HEADER.size :])


def pack_server_frame(frame: ServerFrame) -> bytes:
    if frame.kind not in _FRAME_KINDS:
        raise ValueError("Unsupported sync frame kind")
    cursor = frame.cursor.encode("ascii")
    sender = frame.sender.encode("ascii")
    if len(cursor) > 65_535 or len(sender) > 65_535:
        raise ValueError("Sync frame metadata is too long")
    return (
        _SERVER_HEADER.pack(_SERVER_MAGIC, frame.kind, len(cursor), len(sender))
        + cursor
        + sender
        + frame.payload
    )


def unpack_server_frame(data: bytes) -> ServerFrame:
    if not isinstance(data, bytes) or len(data) < _SERVER_HEADER.size:
        raise ValueError("Invalid server sync frame")
    magic, kind, cursor_length, sender_length = _SERVER_HEADER.unpack_from(data)
    metadata_end = _SERVER_HEADER.size + cursor_length + sender_length
    if magic != _SERVER_MAGIC or kind not in _FRAME_KINDS or metadata_end > len(data):
        raise ValueError("Invalid server sync frame")
    cursor_end = _SERVER_HEADER.size + cursor_length
    try:
        cursor = data[_SERVER_HEADER.size : cursor_end].decode("ascii")
        sender = data[cursor_end:metadata_end].decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("Invalid server sync frame metadata") from exc
    return ServerFrame(kind=kind, cursor=cursor, sender=sender, payload=data[metadata_end:])


@dataclass(frozen=True, slots=True)
class SyncRecord:
    cursor: str
    origin: str
    sender: str
    kind: int
    payload: bytes


@dataclass(frozen=True, slots=True)
class RecoveryBatch:
    snapshot: SyncRecord | None
    records: tuple[SyncRecord, ...]


class RecoveryLimitExceeded(RuntimeError):
    """Raised when one connection would replay an unbounded journal tail."""

    def __init__(self, cursor: str | None, limit: int) -> None:
        super().__init__(f"Sync recovery exceeded the configured limit of {limit} records")
        self.cursor = cursor
        self.limit = limit


_PUBSUB_HEADER = struct.Struct("!BHHH")


def _pack_record(record: SyncRecord) -> bytes:
    cursor = record.cursor.encode("ascii")
    origin = record.origin.encode("ascii")
    sender = record.sender.encode("ascii")
    if max(len(cursor), len(origin), len(sender)) > 65_535:
        raise ValueError("Sync record metadata is too long")
    return (
        _PUBSUB_HEADER.pack(record.kind, len(cursor), len(origin), len(sender))
        + cursor
        + origin
        + sender
        + record.payload
    )


def _unpack_record(data: bytes) -> SyncRecord:
    if len(data) < _PUBSUB_HEADER.size:
        raise ValueError("Invalid Redis sync record")
    kind, cursor_length, origin_length, sender_length = _PUBSUB_HEADER.unpack_from(data)
    cursor_start = _PUBSUB_HEADER.size
    origin_start = cursor_start + cursor_length
    sender_start = origin_start + origin_length
    payload_start = sender_start + sender_length
    if kind not in _FRAME_KINDS or payload_start > len(data):
        raise ValueError("Invalid Redis sync record")
    try:
        return SyncRecord(
            cursor=data[cursor_start:origin_start].decode("ascii"),
            origin=data[origin_start:sender_start].decode("ascii"),
            sender=data[sender_start:payload_start].decode("ascii"),
            kind=kind,
            payload=data[payload_start:],
        )
    except UnicodeDecodeError as exc:
        raise ValueError("Invalid Redis sync record metadata") from exc


def _cursor_tuple(cursor: str) -> tuple[int, int]:
    try:
        milliseconds, sequence = cursor.split("-", 1)
        return int(milliseconds), int(sequence)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("Invalid Redis stream cursor") from exc


class RedisSyncBackend:
    """Redis Pub/Sub fanout plus Stream journaling for encrypted frames."""

    def __init__(
        self,
        url: str | None = None,
        *,
        client: Any | None = None,
        namespace: str = "dhad:sync:v1",
        stream_maxlen: int = 100_000,
        approximate_trim: bool = True,
    ) -> None:
        if stream_maxlen < 1:
            raise ValueError("stream_maxlen must be positive")
        if client is None:
            if Redis is Any:
                raise RuntimeError("redis is required for RedisSyncBackend")
            client = Redis.from_url(
                url or "redis://127.0.0.1:6379/0",
                decode_responses=False,
                health_check_interval=30,
                socket_connect_timeout=3,
                socket_timeout=5,
                retry_on_timeout=True,
            )
            self._owns_client = True
        else:
            self._owns_client = False
        self._redis = client
        self._namespace = namespace.rstrip(":")
        self._stream_maxlen = stream_maxlen
        self._approximate_trim = bool(approximate_trim)

    def _stream_key(self, doc_id: str) -> str:
        return f"{self._namespace}:stream:{doc_id}"

    def _channel_key(self, doc_id: str) -> str:
        return f"{self._namespace}:live:{doc_id}"

    def _snapshot_key(self, doc_id: str) -> str:
        return f"{self._namespace}:snapshot:{doc_id}"

    @staticmethod
    def _from_fields(cursor: str, fields: dict[bytes, bytes]) -> SyncRecord:
        try:
            record = SyncRecord(
                cursor=cursor,
                origin=fields[b"origin"].decode("ascii"),
                sender=fields[b"sender"].decode("ascii"),
                kind=int(fields[b"kind"]),
                payload=bytes(fields[b"payload"]),
            )
        except (KeyError, TypeError, UnicodeDecodeError, ValueError) as exc:
            raise ValueError("Corrupt Redis sync stream entry") from exc
        if record.kind not in _FRAME_KINDS:
            raise ValueError("Corrupt Redis sync stream entry")
        return record

    async def publish(
        self,
        doc_id: str,
        origin: str,
        sender: str,
        kind: int,
        payload: bytes,
    ) -> SyncRecord:
        if kind not in _FRAME_KINDS:
            raise ValueError("Unsupported sync frame kind")
        if not isinstance(payload, bytes):
            raise TypeError("Sync payload must be bytes")
        cursor_value = await self._redis.xadd(
            self._stream_key(doc_id),
            {"origin": origin, "sender": sender, "kind": kind, "payload": payload},
            maxlen=self._stream_maxlen,
            approximate=self._approximate_trim,
        )
        cursor = (
            cursor_value.decode("ascii") if isinstance(cursor_value, bytes) else str(cursor_value)
        )
        record = SyncRecord(cursor, origin, sender, kind, payload)
        if kind == FRAME_SNAPSHOT:
            await self._redis.hset(
                self._snapshot_key(doc_id),
                mapping={
                    "cursor": cursor,
                    "origin": origin,
                    "sender": sender,
                    "kind": kind,
                    "payload": payload,
                },
            )
        await self._redis.publish(self._channel_key(doc_id), _pack_record(record))
        return record

    async def _snapshot(self, doc_id: str) -> SyncRecord | None:
        fields = await self._redis.hgetall(self._snapshot_key(doc_id))
        if not fields:
            return None
        cursor_value = fields.get(b"cursor")
        if cursor_value is None:
            raise ValueError("Corrupt Redis sync snapshot")
        cursor = (
            cursor_value.decode("ascii") if isinstance(cursor_value, bytes) else str(cursor_value)
        )
        return self._from_fields(cursor, fields)

    async def recover(
        self,
        doc_id: str,
        *,
        after_cursor: str | None,
        limit: int = 1_000,
    ) -> RecoveryBatch:
        if limit < 1:
            raise ValueError("Recovery limit must be positive")
        snapshot = await self._snapshot(doc_id)
        selected_snapshot: SyncRecord | None = None
        if snapshot is not None and (
            after_cursor is None or _cursor_tuple(after_cursor) < _cursor_tuple(snapshot.cursor)
        ):
            selected_snapshot = snapshot
            base_cursor = snapshot.cursor
        else:
            base_cursor = after_cursor or "0-0"
            _cursor_tuple(base_cursor)
        entries = await self._redis.xrange(
            self._stream_key(doc_id), min=f"({base_cursor}", max="+", count=limit
        )
        records = []
        for cursor_value, fields in entries:
            cursor = (
                cursor_value.decode("ascii")
                if isinstance(cursor_value, bytes)
                else str(cursor_value)
            )
            records.append(self._from_fields(cursor, fields))
        return RecoveryBatch(selected_snapshot, tuple(records))

    async def subscribe(self, doc_id: str) -> AsyncIterator[SyncRecord]:
        pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
        await pubsub.subscribe(self._channel_key(doc_id))
        try:
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message is None:
                    await asyncio.sleep(0)
                    continue
                data = message.get("data")
                if isinstance(data, bytes):
                    yield _unpack_record(data)
        finally:
            await pubsub.unsubscribe(self._channel_key(doc_id))
            await pubsub.aclose()

    async def close(self) -> None:
        if self._owns_client:
            await self._redis.aclose()


class ConnectionRateLimiter:
    """Non-blocking token bucket scoped to one WebSocket connection."""

    def __init__(
        self,
        rate: int,
        per_seconds: float,
        *,
        clock=time.monotonic,
    ) -> None:
        if rate < 1 or per_seconds <= 0:
            raise ValueError("Connection rate limits must be positive")
        self._capacity = float(rate)
        self._tokens = float(rate)
        self._refill_rate = float(rate) / per_seconds
        self._updated_at = clock()
        self._clock = clock
        self._lock = asyncio.Lock()

    async def allow(self) -> bool:
        async with self._lock:
            now = self._clock()
            elapsed = max(0.0, now - self._updated_at)
            self._tokens = min(self._capacity, self._tokens + elapsed * self._refill_rate)
            self._updated_at = now
            if self._tokens < 1.0:
                return False
            self._tokens -= 1.0
            return True


#: Documents are addressed by opaque ids chosen by clients.
DOC_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

#: Close codes (4000-range is application-reserved by RFC 6455).
CLOSE_BAD_DOC_ID = 4000
CLOSE_ROOM_FULL = 4001
CLOSE_BAD_MESSAGE = 4002
CLOSE_PAYLOAD_TOO_LARGE = 4003
CLOSE_RATE_LIMIT = 4004
CLOSE_SLOW_PEER = 4005
CLOSE_UNAUTHORIZED = 4006
CLOSE_FORBIDDEN_ORIGIN = 4007
CLOSE_RECOVERY_LIMIT = 4008


@dataclass(frozen=True, slots=True)
class SyncSettings:
    max_payload_bytes: int = 262_144
    max_peers_per_doc: int = 128
    outgoing_queue_size: int = 256
    send_timeout_seconds: float = 5.0
    messages_per_window: int = 240
    rate_window_seconds: float = 60.0
    recovery_limit: int = 1_000
    max_recovery_records: int = 10_000

    def __post_init__(self) -> None:
        values = (
            self.max_payload_bytes,
            self.max_peers_per_doc,
            self.outgoing_queue_size,
            self.messages_per_window,
            self.recovery_limit,
            self.max_recovery_records,
        )
        if any(value < 1 for value in values):
            raise ValueError("Sync integer limits must be positive")
        if self.send_timeout_seconds <= 0 or self.rate_window_seconds <= 0:
            raise ValueError("Sync time limits must be positive")

    @classmethod
    def from_env(cls) -> "SyncSettings":
        def integer(name: str, default: int) -> int:
            raw = os.environ.get(name)
            if raw is None:
                return default
            try:
                return int(raw)
            except ValueError as exc:
                raise ValueError(f"{name} must be an integer") from exc

        def floating(name: str, default: float) -> float:
            raw = os.environ.get(name)
            if raw is None:
                return default
            try:
                return float(raw)
            except ValueError as exc:
                raise ValueError(f"{name} must be a number") from exc

        return cls(
            max_payload_bytes=integer("DHAD_SYNC_MAX_PAYLOAD_BYTES", 262_144),
            max_peers_per_doc=integer("DHAD_SYNC_MAX_PEERS", 128),
            outgoing_queue_size=integer("DHAD_SYNC_OUTGOING_QUEUE", 256),
            send_timeout_seconds=floating("DHAD_SYNC_SEND_TIMEOUT_SECONDS", 5.0),
            messages_per_window=integer("DHAD_SYNC_MESSAGES_PER_WINDOW", 240),
            rate_window_seconds=floating("DHAD_SYNC_RATE_WINDOW_SECONDS", 60.0),
            recovery_limit=integer("DHAD_SYNC_RECOVERY_LIMIT", 1_000),
            max_recovery_records=integer("DHAD_SYNC_MAX_RECOVERY_RECORDS", 10_000),
        )


# Compatibility constants now reflect the vMAX binary limits.
MAX_PAYLOAD_CHARS = 262_144
MAX_PEERS_PER_DOC = 128


@dataclass
class _MemoryDocument:
    records: list[SyncRecord] = field(default_factory=list)
    snapshot: SyncRecord | None = None
    subscribers: set[asyncio.Queue[SyncRecord]] = field(default_factory=set)
    sequence: int = 0


class InMemorySyncBackend:
    """Journaled local backend with the same contract as Redis.

    It is intended for tests and single-process development. Production
    multi-worker deployments select :class:`RedisSyncBackend` explicitly.
    """

    def __init__(self, *, stream_maxlen: int = 10_000) -> None:
        if stream_maxlen < 1:
            raise ValueError("stream_maxlen must be positive")
        self._stream_maxlen = stream_maxlen
        self._documents: dict[str, _MemoryDocument] = {}
        self._lock = asyncio.Lock()

    async def publish(
        self,
        doc_id: str,
        origin: str,
        sender: str,
        kind: int,
        payload: bytes,
    ) -> SyncRecord:
        if kind not in _FRAME_KINDS:
            raise ValueError("Unsupported sync frame kind")
        if not isinstance(payload, bytes):
            raise TypeError("Sync payload must be bytes")
        async with self._lock:
            document = self._documents.setdefault(doc_id, _MemoryDocument())
            document.sequence += 1
            record = SyncRecord(
                cursor=f"{document.sequence}-0",
                origin=origin,
                sender=sender,
                kind=kind,
                payload=bytes(payload),
            )
            document.records.append(record)
            if len(document.records) > self._stream_maxlen:
                del document.records[: len(document.records) - self._stream_maxlen]
            if kind == FRAME_SNAPSHOT:
                document.snapshot = record
            subscribers = tuple(document.subscribers)
        for queue in subscribers:
            try:
                queue.put_nowait(record)
            except asyncio.QueueFull:
                # Pub/Sub is deliberately lossy; the Stream journal is the
                # recovery source after a subscriber reconnects.
                continue
        return record

    async def recover(
        self,
        doc_id: str,
        *,
        after_cursor: str | None,
        limit: int = 1_000,
    ) -> RecoveryBatch:
        if limit < 1:
            raise ValueError("Recovery limit must be positive")
        async with self._lock:
            document = self._documents.get(doc_id)
            if document is None:
                return RecoveryBatch(None, ())
            snapshot = document.snapshot
            selected = None
            if snapshot is not None and (
                after_cursor is None or _cursor_tuple(after_cursor) < _cursor_tuple(snapshot.cursor)
            ):
                selected = snapshot
                base = snapshot.cursor
            else:
                base = after_cursor or "0-0"
                _cursor_tuple(base)
            records = tuple(
                record
                for record in document.records
                if _cursor_tuple(record.cursor) > _cursor_tuple(base)
            )[:limit]
            return RecoveryBatch(selected, records)

    async def subscribe(self, doc_id: str) -> AsyncIterator[SyncRecord]:
        queue: asyncio.Queue[SyncRecord] = asyncio.Queue(maxsize=2_048)
        async with self._lock:
            document = self._documents.setdefault(doc_id, _MemoryDocument())
            document.subscribers.add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            async with self._lock:
                document = self._documents.get(doc_id)
                if document is not None:
                    document.subscribers.discard(queue)

    async def close(self) -> None:
        return None


OutgoingFrame = bytes | dict[str, object]


class _CursorFrame(bytes):
    """Bytes-compatible queue item carrying its durable stream cursor."""

    def __new__(cls, payload: bytes, cursor: str):
        value = super().__new__(cls, payload)
        value.cursor = cursor
        return value


@dataclass(slots=True)
class PeerConnection:
    client_id: str
    socket: WebSocket | None
    queue: asyncio.Queue[OutgoingFrame]
    delivered_cursor: str | None = None

    @classmethod
    def create(cls, client_id: str, socket: WebSocket, *, queue_size: int) -> "PeerConnection":
        return cls(client_id, socket, asyncio.Queue(maxsize=queue_size))

    @classmethod
    def for_test(cls, client_id: str, *, queue_size: int) -> "PeerConnection":
        return cls(client_id, None, asyncio.Queue(maxsize=queue_size))

    def offer(self, frame: OutgoingFrame, *, cursor: str | None = None) -> bool:
        queued: OutgoingFrame = frame
        if cursor is not None:
            if not isinstance(frame, bytes):
                raise TypeError("Only binary sync frames may carry a cursor")
            _cursor_tuple(cursor)
            queued = _CursorFrame(frame, cursor)
        try:
            self.queue.put_nowait(queued)
            return True
        except asyncio.QueueFull:
            return False

    def note_delivered(self, cursor: str) -> None:
        _cursor_tuple(cursor)
        if self.delivered_cursor is None or _cursor_tuple(cursor) > _cursor_tuple(
            self.delivered_cursor
        ):
            self.delivered_cursor = cursor

    def _already_delivered(self, cursor: str | None) -> bool:
        return (
            cursor is not None
            and self.delivered_cursor is not None
            and _cursor_tuple(cursor) <= _cursor_tuple(self.delivered_cursor)
        )

    async def send_loop(self, timeout: float) -> None:
        if self.socket is None:
            raise RuntimeError("Test peers cannot run a WebSocket writer")
        while True:
            frame = await self.queue.get()
            cursor = getattr(frame, "cursor", None)
            if self._already_delivered(cursor):
                continue
            if isinstance(frame, bytes):
                operation = self.socket.send_bytes(frame)
            else:
                operation = self.socket.send_json(frame)
            await asyncio.wait_for(operation, timeout=timeout)
            if cursor is not None:
                self.note_delivered(cursor)


@dataclass(slots=True)
class _Room:
    peers: dict[str, PeerConnection] = field(default_factory=dict)
    listener_task: asyncio.Task[None] | None = None
    listener_cursor: str | None = None


@dataclass(frozen=True, slots=True)
class JoinResult:
    peer: PeerConnection
    peer_count: int
    recovery: RecoveryBatch


class SyncHub:
    """Local connection registry backed by a durable cross-node event bus."""

    def __init__(
        self,
        backend: Any | None = None,
        *,
        settings: SyncSettings | None = None,
        node_id: str | None = None,
    ) -> None:
        self.backend = backend or InMemorySyncBackend()
        self.settings = settings or SyncSettings()
        self.node_id = node_id or secrets.token_urlsafe(12)
        self._rooms: dict[str, _Room] = {}
        self._lock = asyncio.Lock()
        self._closed = False
        self._background_tasks: set[asyncio.Task[None]] = set()

    def _spawn_background(self, coroutine: Any, *, name: str) -> None:
        """Track fire-and-forget maintenance so shutdown is deterministic."""

        task = asyncio.create_task(coroutine, name=name)
        self._background_tasks.add(task)

        def completed(done: asyncio.Task[None]) -> None:
            self._background_tasks.discard(done)
            if done.cancelled():
                return
            try:
                done.result()
            except Exception:
                logger.exception("Dhad sync background task failed", extra={"task": name})

        task.add_done_callback(completed)

    async def _listen(self, doc_id: str) -> None:
        delay = 0.1
        while True:
            try:
                async for record in self.backend.subscribe(doc_id):
                    delay = 0.1
                    if record.origin != self.node_id:
                        await self._fanout(doc_id, record)
                    await self._note_cursor(doc_id, record.cursor)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - Redis reconnects via bounded backoff
                try:
                    cursor = await self._room_cursor(doc_id)
                    async for record in iter_recovery_records(
                        self.backend,
                        doc_id,
                        after_cursor=cursor or "0-0",
                        batch_size=self.settings.recovery_limit,
                    ):
                        if record.origin != self.node_id:
                            await self._fanout(doc_id, record)
                        await self._note_cursor(doc_id, record.cursor)
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001 - Redis may still be unavailable
                    logger.warning(
                        "Dhad sync recovery after Pub/Sub failure was unsuccessful",
                        extra={"document": hashlib.sha256(doc_id.encode()).hexdigest()[:12]},
                        exc_info=True,
                    )
                jitter = secrets.randbelow(100) / 1_000
                await asyncio.sleep(delay + jitter)
                delay = min(delay * 2, 5.0)

    async def _room_cursor(self, doc_id: str) -> str | None:
        async with self._lock:
            room = self._rooms.get(doc_id)
            return None if room is None else room.listener_cursor

    async def _note_cursor(self, doc_id: str, cursor: str) -> None:
        async with self._lock:
            room = self._rooms.get(doc_id)
            if room is not None and (
                room.listener_cursor is None
                or _cursor_tuple(cursor) > _cursor_tuple(room.listener_cursor)
            ):
                room.listener_cursor = cursor

    async def join(
        self,
        doc_id: str,
        socket: WebSocket,
        *,
        after_cursor: str | None,
    ) -> JoinResult | None:
        created_listener = False
        async with self._lock:
            if self._closed:
                return None
            room = self._rooms.setdefault(doc_id, _Room())
            if len(room.peers) >= self.settings.max_peers_per_doc:
                return None
            if room.listener_task is None:
                room.listener_task = asyncio.create_task(
                    self._listen(doc_id), name=f"dhad-sync-{doc_id}"
                )
                created_listener = True
            client_id = secrets.token_urlsafe(12)
            peer = PeerConnection.create(
                client_id, socket, queue_size=self.settings.outgoing_queue_size
            )
            room.peers[client_id] = peer
            peer_count = len(room.peers)
        if created_listener:
            # Let the subscription coroutine register before this node accepts
            # a publisher. Local fanout remains immediate regardless.
            await asyncio.sleep(0)
        try:
            recovery = await self.backend.recover(
                doc_id,
                after_cursor=after_cursor,
                limit=self.settings.recovery_limit,
            )
        except Exception:
            await self.leave(doc_id, client_id)
            raise
        return JoinResult(peer, peer_count, recovery)

    async def leave(self, doc_id: str, client_id: str) -> int:
        listener: asyncio.Task[None] | None = None
        async with self._lock:
            room = self._rooms.get(doc_id)
            if room is None:
                return 0
            room.peers.pop(client_id, None)
            remaining = len(room.peers)
            if not room.peers:
                listener = room.listener_task
                del self._rooms[doc_id]
        if listener is not None:
            listener.cancel()
            await asyncio.gather(listener, return_exceptions=True)
        return remaining

    async def _evict_slow(self, doc_id: str, peer: PeerConnection) -> None:
        await self.leave(doc_id, peer.client_id)
        if peer.socket is not None:
            try:
                await asyncio.wait_for(
                    peer.socket.close(code=CLOSE_SLOW_PEER),
                    timeout=self.settings.send_timeout_seconds,
                )
            except Exception:  # noqa: BLE001 - peer is already unusable
                logger.debug("Failed to close an already unusable sync peer", exc_info=True)

    async def _fanout(self, doc_id: str, record: SyncRecord) -> None:
        async with self._lock:
            room = self._rooms.get(doc_id)
            peers = () if room is None else tuple(room.peers.values())
        frame = pack_server_frame(
            ServerFrame(record.kind, record.cursor, record.sender, record.payload)
        )
        for peer in peers:
            if record.origin == self.node_id and peer.client_id == record.sender:
                continue
            if not peer.offer(frame, cursor=record.cursor):
                self._spawn_background(
                    self._evict_slow(doc_id, peer),
                    name=f"dhad-sync-evict-{peer.client_id}",
                )

    async def publish(self, doc_id: str, sender: str, frame: ClientFrame) -> SyncRecord:
        record = await self.backend.publish(doc_id, self.node_id, sender, frame.kind, frame.payload)
        await self._fanout(doc_id, record)
        return record

    async def room_size(self, doc_id: str) -> int:
        async with self._lock:
            room = self._rooms.get(doc_id)
            return 0 if room is None else len(room.peers)

    async def close(self) -> None:
        async with self._lock:
            self._closed = True
            tasks = [
                room.listener_task
                for room in self._rooms.values()
                if room.listener_task is not None
            ]
            tasks.extend(self._background_tasks)
            self._background_tasks.clear()
            self._rooms.clear()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.backend.close()


def _recovery_frames(batch: RecoveryBatch) -> tuple[bytes, ...]:
    records = (() if batch.snapshot is None else (batch.snapshot,)) + batch.records
    return tuple(
        pack_server_frame(ServerFrame(item.kind, item.cursor, item.sender, item.payload))
        for item in records
    )


async def iter_recovery_records(
    backend: Any,
    doc_id: str,
    *,
    after_cursor: str | None,
    batch_size: int,
    initial_batch: RecoveryBatch | None = None,
    max_records: int | None = None,
) -> AsyncIterator[SyncRecord]:
    """Page a finite Stream tail without buffering the full journal in RAM."""

    if batch_size < 1:
        raise ValueError("Recovery batch_size must be positive")
    if max_records is not None and max_records < 1:
        raise ValueError("Recovery max_records must be positive")
    cursor = after_cursor
    batch = initial_batch
    emitted = 0

    def account() -> None:
        nonlocal emitted
        if max_records is not None and emitted >= max_records:
            raise RecoveryLimitExceeded(cursor, max_records)
        emitted += 1

    while True:
        if batch is None:
            batch = await backend.recover(
                doc_id,
                after_cursor=cursor,
                limit=batch_size,
            )
        if batch.snapshot is not None:
            account()
            yield batch.snapshot
            cursor = batch.snapshot.cursor
        for record in batch.records:
            account()
            yield record
            cursor = record.cursor
        if len(batch.records) < batch_size:
            return
        if not batch.records:
            return
        batch = None


def _websocket_api_key(websocket: WebSocket) -> str | None:
    direct = websocket.headers.get("x-api-key")
    if direct and direct.strip():
        return direct.strip()
    authorization = websocket.headers.get("authorization", "")
    scheme, _, credential = authorization.partition(" ")
    if scheme.lower() == "bearer" and credential.strip():
        return credential.strip()
    return None


def create_sync_router(
    hub: SyncHub | None = None,
    *,
    backend: Any | None = None,
    settings: SyncSettings | None = None,
    api_keys: tuple[str, ...] = (),
    allowed_origins: tuple[str, ...] = (),
    allowed_origin_regex: str | None = None,
) -> APIRouter:
    """Build the vMAX binary sync router around a durable backend."""

    active_hub = hub or SyncHub(backend, settings=settings)
    key_hashes = tuple(hashlib.sha256(value.encode("utf-8")).digest() for value in api_keys)
    trusted_origins = frozenset(value.rstrip("/") for value in allowed_origins)
    origin_pattern = re.compile(allowed_origin_regex) if allowed_origin_regex else None
    router = APIRouter()
    router.hub = active_hub  # type: ignore[attr-defined] — lifecycle/test access

    @router.websocket("/ws/sync/{doc_id}")
    async def sync_endpoint(websocket: WebSocket, doc_id: str) -> None:
        if not DOC_ID_RE.fullmatch(doc_id):
            await websocket.close(code=CLOSE_BAD_DOC_ID)
            return
        origin = websocket.headers.get("origin")
        if origin is not None and (
            origin.rstrip("/") not in trusted_origins
            and (origin_pattern is None or origin_pattern.fullmatch(origin) is None)
        ):
            await websocket.close(code=CLOSE_FORBIDDEN_ORIGIN)
            return
        if key_hashes:
            presented = _websocket_api_key(websocket)
            if presented is None:
                authorized = False
            else:
                digest = hashlib.sha256(presented.encode("utf-8")).digest()
                authorized = any(hmac.compare_digest(digest, expected) for expected in key_hashes)
            if not authorized:
                await websocket.close(code=CLOSE_UNAUTHORIZED)
                return
        cursor = websocket.query_params.get("cursor")
        if cursor is not None:
            try:
                _cursor_tuple(cursor)
            except ValueError:
                await websocket.close(code=CLOSE_BAD_MESSAGE)
                return
        await websocket.accept()
        try:
            joined = await active_hub.join(doc_id, websocket, after_cursor=cursor)
        except Exception:
            await websocket.close(code=1013)
            return
        if joined is None:
            await websocket.close(code=CLOSE_ROOM_FULL)
            return
        peer = joined.peer
        try:
            await websocket.send_json(
                {
                    "type": "joined",
                    "protocol": "dhad-sync-v4",
                    "doc_id": doc_id,
                    "client_id": peer.client_id,
                    "peers": joined.peer_count,
                }
            )
        except Exception:
            await active_hub.leave(doc_id, peer.client_id)
            return
        try:
            async for record in iter_recovery_records(
                active_hub.backend,
                doc_id,
                after_cursor=cursor,
                batch_size=active_hub.settings.recovery_limit,
                initial_batch=joined.recovery,
                max_records=active_hub.settings.max_recovery_records,
            ):
                frame = pack_server_frame(
                    ServerFrame(record.kind, record.cursor, record.sender, record.payload)
                )
                await asyncio.wait_for(
                    websocket.send_bytes(frame),
                    timeout=active_hub.settings.send_timeout_seconds,
                )
                peer.note_delivered(record.cursor)
        except RecoveryLimitExceeded:
            await active_hub.leave(doc_id, peer.client_id)
            await websocket.close(code=CLOSE_RECOVERY_LIMIT)
            return
        except Exception:
            await active_hub.leave(doc_id, peer.client_id)
            await websocket.close(code=CLOSE_SLOW_PEER)
            return

        async def writer() -> None:
            try:
                await peer.send_loop(active_hub.settings.send_timeout_seconds)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - isolate this peer's socket failure
                await active_hub._evict_slow(doc_id, peer)

        writer_task = asyncio.create_task(writer(), name=f"dhad-ws-writer-{peer.client_id}")
        limiter = ConnectionRateLimiter(
            active_hub.settings.messages_per_window,
            active_hub.settings.rate_window_seconds,
        )
        try:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    break
                if not await limiter.allow():
                    await websocket.close(code=CLOSE_RATE_LIMIT)
                    return
                payload = message.get("bytes")
                if payload is not None:
                    if len(payload) > (active_hub.settings.max_payload_bytes + _CLIENT_HEADER.size):
                        await websocket.close(code=CLOSE_PAYLOAD_TOO_LARGE)
                        return
                    try:
                        frame = unpack_client_frame(payload)
                    except ValueError:
                        await websocket.close(code=CLOSE_BAD_MESSAGE)
                        return
                    if len(frame.payload) > active_hub.settings.max_payload_bytes:
                        await websocket.close(code=CLOSE_PAYLOAD_TOO_LARGE)
                        return
                    await active_hub.publish(doc_id, peer.client_id, frame)
                    continue
                text_payload = message.get("text")
                if text_payload is not None:
                    try:
                        control = json.loads(text_payload)
                    except (TypeError, json.JSONDecodeError):
                        control = None
                    if control == {"type": "ping"}:
                        await websocket.send_json({"type": "pong"})
                        continue
                await websocket.close(code=CLOSE_BAD_MESSAGE)
                return
        except (WebSocketDisconnect, asyncio.CancelledError):
            # ASGI servers may cancel the route task while a client context is
            # closing. Treat that cancellation as a normal disconnect after
            # running the same deterministic peer cleanup below.
            pass
        finally:
            async def cleanup_peer() -> None:
                writer_task.cancel()
                await asyncio.gather(writer_task, return_exceptions=True)
                await active_hub.leave(doc_id, peer.client_id)

            cleanup_task = asyncio.create_task(
                cleanup_peer(), name=f"dhad-ws-cleanup-{peer.client_id}"
            )
            try:
                await asyncio.shield(cleanup_task)
            except asyncio.CancelledError:
                # Test clients and ASGI servers may cancel the endpoint while
                # the WebSocket context is closing. Keep cleanup detached and
                # consume its result so normal disconnects do not surface as
                # application failures.
                def consume_cleanup_result(done: asyncio.Task[None]) -> None:
                    if done.cancelled():
                        return
                    try:
                        done.result()
                    except Exception:
                        logger.debug("WebSocket peer cleanup failed", exc_info=True)

                cleanup_task.add_done_callback(consume_cleanup_result)

    return router
