"""vMAX Phase 4 acceptance tests for durable opaque synchronization."""

from __future__ import annotations

import asyncio

import fakeredis.aioredis
import pytest

import dhad.sync as sync


@pytest.mark.anyio
async def test_redis_stream_journals_and_resumes_from_cursor() -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    backend = sync.RedisSyncBackend(client=redis, namespace="phase4", stream_maxlen=100)

    first = await backend.publish("doc", "node-a", "alice", sync.FRAME_UPDATE, b"cipher-1")
    second = await backend.publish("doc", "node-b", "bob", sync.FRAME_UPDATE, b"cipher-2")

    recovered = await backend.recover("doc", after_cursor=first.cursor)
    assert [record.cursor for record in recovered.records] == [second.cursor]
    assert recovered.records[0].payload == b"cipher-2"
    await backend.close()


@pytest.mark.anyio
async def test_redis_pubsub_fans_out_opaque_payload_byte_exact() -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    producer = sync.RedisSyncBackend(client=redis, namespace="fanout")
    consumer = sync.RedisSyncBackend(client=redis, namespace="fanout")
    subscription = consumer.subscribe("doc")
    pending = asyncio.create_task(anext(subscription))
    await asyncio.sleep(0)

    ciphertext = bytes(range(256)) * 8
    published = await producer.publish("doc", "node-a", "alice", sync.FRAME_UPDATE, ciphertext)
    received = await asyncio.wait_for(pending, timeout=1)

    assert received.cursor == published.cursor
    assert received.payload == ciphertext
    await subscription.aclose()
    await producer.close()
    await consumer.close()


@pytest.mark.anyio
async def test_latest_encrypted_snapshot_seeds_recovery() -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    backend = sync.RedisSyncBackend(client=redis, namespace="snapshots", stream_maxlen=100)
    await backend.publish("doc", "node", "alice", sync.FRAME_UPDATE, b"old")
    snapshot = await backend.publish(
        "doc", "node", "alice", sync.FRAME_SNAPSHOT, b"encrypted-full-state"
    )
    tail = await backend.publish("doc", "node", "bob", sync.FRAME_UPDATE, b"tail")

    recovery = await backend.recover("doc", after_cursor=None)

    assert recovery.snapshot == snapshot
    assert [record.cursor for record in recovery.records] == [tail.cursor]
    await backend.close()


@pytest.mark.anyio
async def test_recovery_iterator_pages_until_journal_tail() -> None:
    backend = sync.InMemorySyncBackend(stream_maxlen=100)
    for value in (b"one", b"two", b"three"):
        await backend.publish("doc", "node", "writer", sync.FRAME_UPDATE, value)

    records = [
        record
        async for record in sync.iter_recovery_records(
            backend, "doc", after_cursor="0-0", batch_size=1
        )
    ]

    assert [record.payload for record in records] == [b"one", b"two", b"three"]


class _SocketStub:
    def __init__(self) -> None:
        self.closed_with = None

    async def close(self, *, code: int) -> None:
        self.closed_with = code


@pytest.mark.anyio
async def test_slow_peer_is_evicted_without_blocking_healthy_mailbox() -> None:
    settings = sync.SyncSettings(outgoing_queue_size=1, max_peers_per_doc=3)
    hub = sync.SyncHub(sync.InMemorySyncBackend(), settings=settings, node_id="node")
    sender = await hub.join("doc", _SocketStub(), after_cursor=None)
    slow = await hub.join("doc", _SocketStub(), after_cursor=None)
    healthy = await hub.join("doc", _SocketStub(), after_cursor=None)
    assert sender is not None and slow is not None and healthy is not None
    assert slow.peer.offer(b"already-full")

    await hub.publish("doc", sender.peer.client_id, sync.ClientFrame(sync.FRAME_UPDATE, b"x"))
    for _ in range(10):
        if await hub.room_size("doc") == 2:
            break
        await asyncio.sleep(0)

    assert await hub.room_size("doc") == 2
    assert healthy.peer.queue.qsize() == 1
    assert slow.peer.socket.closed_with == sync.CLOSE_SLOW_PEER
    await hub.close()


@pytest.mark.anyio
async def test_fanout_queues_two_thousand_connections_without_socket_io() -> None:
    settings = sync.SyncSettings(
        outgoing_queue_size=2,
        max_peers_per_doc=2_000,
        recovery_limit=10,
    )
    hub = sync.SyncHub(sync.InMemorySyncBackend(), settings=settings, node_id="load-node")
    peers = []
    for _ in range(2_000):
        joined = await hub.join("large-room", _SocketStub(), after_cursor=None)
        assert joined is not None
        peers.append(joined.peer)

    await hub.publish(
        "large-room",
        peers[0].client_id,
        sync.ClientFrame(sync.FRAME_UPDATE, b"encrypted-update"),
    )

    assert peers[0].queue.qsize() == 0
    assert all(peer.queue.qsize() == 1 for peer in peers[1:])
    await hub.close()


@pytest.mark.anyio
async def test_two_hubs_fan_out_across_redis_pubsub() -> None:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    first_backend = sync.RedisSyncBackend(client=redis, namespace="cluster")
    second_backend = sync.RedisSyncBackend(client=redis, namespace="cluster")
    first_hub = sync.SyncHub(first_backend, node_id="node-a")
    second_hub = sync.SyncHub(second_backend, node_id="node-b")
    sender = await first_hub.join("doc", _SocketStub(), after_cursor=None)
    receiver = await second_hub.join("doc", _SocketStub(), after_cursor=None)
    assert sender is not None and receiver is not None

    await first_hub.publish(
        "doc",
        sender.peer.client_id,
        sync.ClientFrame(sync.FRAME_UPDATE, b"cross-node-ciphertext"),
    )
    for _ in range(100):
        if receiver.peer.queue.qsize():
            break
        await asyncio.sleep(0.001)

    relayed = sync.unpack_server_frame(receiver.peer.queue.get_nowait())
    assert relayed.payload == b"cross-node-ciphertext"
    await first_hub.close()
    await second_hub.close()


class _FlakySubscriptionBackend:
    def __init__(self) -> None:
        self.first = sync.SyncRecord("1-0", "remote", "alice", sync.FRAME_UPDATE, b"live")
        self.missed = sync.SyncRecord("2-0", "remote", "alice", sync.FRAME_UPDATE, b"missed")
        self.subscribe_calls = 0

    async def publish(self, *args):  # pragma: no cover - listener-only fixture
        raise AssertionError(args)

    async def recover(self, _doc_id, *, after_cursor, limit):
        del limit
        if after_cursor == self.first.cursor:
            return sync.RecoveryBatch(None, (self.missed,))
        return sync.RecoveryBatch(None, ())

    async def subscribe(self, _doc_id):
        self.subscribe_calls += 1
        if self.subscribe_calls == 1:
            yield self.first
            raise ConnectionError("simulated pubsub disconnect")
        while True:
            await asyncio.sleep(60)

    async def close(self):
        return None


@pytest.mark.anyio
async def test_pubsub_reconnect_recovers_gap_from_stream_cursor() -> None:
    backend = _FlakySubscriptionBackend()
    hub = sync.SyncHub(backend, node_id="local")
    joined = await hub.join("doc", _SocketStub(), after_cursor=None)
    assert joined is not None

    for _ in range(300):
        if joined.peer.queue.qsize() == 2:
            break
        await asyncio.sleep(0.001)

    payloads = [sync.unpack_server_frame(joined.peer.queue.get_nowait()).payload for _ in range(2)]
    assert payloads == [b"live", b"missed"]
    for _ in range(300):
        if backend.subscribe_calls >= 2:
            break
        await asyncio.sleep(0.001)
    assert backend.subscribe_calls >= 2
    await hub.close()


def test_binary_wire_frames_preserve_ciphertext_without_json_or_base64() -> None:
    opaque = b"\x00\xff\x80ciphertext\x00"
    client = sync.ClientFrame(kind=sync.FRAME_UPDATE, payload=opaque)
    assert sync.unpack_client_frame(sync.pack_client_frame(client)) == client

    server = sync.ServerFrame(
        kind=sync.FRAME_UPDATE,
        cursor="18446744073709551615-0",
        sender="peer_abc",
        payload=opaque,
    )
    assert sync.unpack_server_frame(sync.pack_server_frame(server)) == server


@pytest.mark.anyio
async def test_connection_rate_limiter_rejects_burst_without_sleeping() -> None:
    limiter = sync.ConnectionRateLimiter(rate=2, per_seconds=60)
    assert await limiter.allow()
    assert await limiter.allow()
    assert not await limiter.allow()


def test_sync_settings_load_strict_environment_limits(monkeypatch) -> None:
    monkeypatch.setenv("DHAD_SYNC_MAX_PAYLOAD_BYTES", "8192")
    monkeypatch.setenv("DHAD_SYNC_MAX_PEERS", "64")
    monkeypatch.setenv("DHAD_SYNC_OUTGOING_QUEUE", "32")
    monkeypatch.setenv("DHAD_SYNC_SEND_TIMEOUT_SECONDS", "1.5")
    monkeypatch.setenv("DHAD_SYNC_MESSAGES_PER_WINDOW", "90")
    monkeypatch.setenv("DHAD_SYNC_RATE_WINDOW_SECONDS", "30")
    monkeypatch.setenv("DHAD_SYNC_RECOVERY_LIMIT", "500")

    settings = sync.SyncSettings.from_env()

    assert settings.max_payload_bytes == 8192
    assert settings.max_peers_per_doc == 64
    assert settings.outgoing_queue_size == 32
    assert settings.send_timeout_seconds == 1.5
    assert settings.messages_per_window == 90
    assert settings.rate_window_seconds == 30
    assert settings.recovery_limit == 500
