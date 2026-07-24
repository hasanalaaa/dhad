"""Stable ASGI tests for the encrypted v4 synchronization surface."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from dhad import Dhad
from dhad.server import create_app
from dhad.sync import (
    CLOSE_BAD_DOC_ID,
    CLOSE_BAD_MESSAGE,
    CLOSE_PAYLOAD_TOO_LARGE,
    CLOSE_RECOVERY_LIMIT,
    FRAME_UPDATE,
    ClientFrame,
    InMemorySyncBackend,
    PeerConnection,
    RecoveryLimitExceeded,
    SyncSettings,
    iter_recovery_records,
    pack_client_frame,
    unpack_server_frame,
)


@pytest.fixture(scope="module")
def client():
    application = create_app(
        engine=Dhad(),
        serve_web=False,
        sync_backend=InMemorySyncBackend(),
    )
    with TestClient(application) as test_client:
        yield test_client


def test_join_handshake_declares_v4_protocol(client) -> None:
    with client.websocket_connect("/ws/sync/doc-a") as socket:
        joined = socket.receive_json()
        assert joined["type"] == "joined"
        assert joined["protocol"] == "dhad-sync-v4"
        assert joined["doc_id"] == "doc-a"


def test_binary_encrypted_payload_reaches_only_other_peer(client) -> None:
    with client.websocket_connect("/ws/sync/doc-b") as first:
        first.receive_json()
        with client.websocket_connect("/ws/sync/doc-b") as second:
            second.receive_json()
            ciphertext = b"\x00\xffopaque"
            first.send_bytes(pack_client_frame(ClientFrame(FRAME_UPDATE, ciphertext)))
            assert unpack_server_frame(second.receive_bytes()).payload == ciphertext
            first.send_json({"type": "ping"})
            assert first.receive_json() == {"type": "pong"}


def test_invalid_document_and_plaintext_frames_are_rejected(client) -> None:
    with pytest.raises(WebSocketDisconnect) as invalid_doc:
        with client.websocket_connect("/ws/sync/bad%20id!"):
            pass
    assert invalid_doc.value.code == CLOSE_BAD_DOC_ID

    with pytest.raises(WebSocketDisconnect) as plaintext:
        with client.websocket_connect("/ws/sync/plaintext") as socket:
            socket.receive_json()
            socket.send_json({"type": "op", "payload": "not encrypted"})
            socket.receive_json()
    assert plaintext.value.code == CLOSE_BAD_MESSAGE


def test_oversized_ciphertext_is_rejected() -> None:
    settings = SyncSettings(max_payload_bytes=32)
    application = create_app(
        engine=Dhad(),
        serve_web=False,
        sync_backend=InMemorySyncBackend(),
        sync_settings=settings,
    )
    with TestClient(application) as test_client:
        with pytest.raises(WebSocketDisconnect) as closed:
            with test_client.websocket_connect("/ws/sync/large") as socket:
                socket.receive_json()
                socket.send_bytes(pack_client_frame(ClientFrame(FRAME_UPDATE, b"x" * 33)))
                socket.receive_json()
        assert closed.value.code == CLOSE_PAYLOAD_TOO_LARGE



@pytest.mark.anyio
async def test_recovery_iterator_enforces_a_hard_record_budget() -> None:
    backend = InMemorySyncBackend(stream_maxlen=100)
    for value in (b"one", b"two", b"three"):
        await backend.publish("doc", "node", "writer", FRAME_UPDATE, value)

    recovered = []
    with pytest.raises(RecoveryLimitExceeded) as exceeded:
        async for record in iter_recovery_records(
            backend,
            "doc",
            after_cursor="0-0",
            batch_size=1,
            max_records=2,
        ):
            recovered.append(record.payload)

    assert recovered == [b"one", b"two"]
    assert exceeded.value.cursor == "2-0"


class _WriterSocket:
    def __init__(self) -> None:
        self.binary = []

    async def send_bytes(self, frame: bytes) -> None:
        self.binary.append(bytes(frame))

    async def send_json(self, frame: dict[str, object]) -> None:
        raise AssertionError(frame)


@pytest.mark.anyio
async def test_peer_writer_drops_live_duplicates_already_delivered_by_recovery() -> None:
    socket = _WriterSocket()
    peer = PeerConnection.create("peer", socket, queue_size=4)
    peer.note_delivered("1-0")
    assert peer.offer(b"duplicate", cursor="1-0")
    assert peer.offer(b"fresh", cursor="2-0")
    writer = asyncio.create_task(peer.send_loop(1.0))
    for _ in range(20):
        if socket.binary:
            break
        await asyncio.sleep(0)
    writer.cancel()
    await asyncio.gather(writer, return_exceptions=True)
    assert socket.binary == [b"fresh"]
    assert peer.delivered_cursor == "2-0"


def test_websocket_recovery_limit_closes_a_client_instead_of_chasing_an_unbounded_tail() -> None:
    settings = SyncSettings(recovery_limit=1, max_recovery_records=2)
    application = create_app(
        engine=Dhad(),
        serve_web=False,
        sync_backend=InMemorySyncBackend(stream_maxlen=100),
        sync_settings=settings,
    )
    with TestClient(application) as test_client:
        with test_client.websocket_connect("/ws/sync/limited") as writer:
            writer.receive_json()
            for value in (b"one", b"two", b"three"):
                writer.send_bytes(pack_client_frame(ClientFrame(FRAME_UPDATE, value)))

        with pytest.raises(WebSocketDisconnect) as closed:
            with test_client.websocket_connect("/ws/sync/limited?cursor=0-0") as reader:
                reader.receive_json()
                reader.receive_bytes()
                reader.receive_bytes()
                reader.receive_bytes()
        assert closed.value.code == CLOSE_RECOVERY_LIMIT
