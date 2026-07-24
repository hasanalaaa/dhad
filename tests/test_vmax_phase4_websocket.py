"""End-to-end ASGI tests for the vMAX encrypted WebSocket protocol."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from dhad import Dhad
from dhad.server import create_app
from dhad.security import SecuritySettings
import dhad.sync as sync


def _client_frame(payload: bytes, kind: int | None = None) -> bytes:
    return sync.pack_client_frame(sync.ClientFrame(kind=kind or sync.FRAME_UPDATE, payload=payload))


def _app(**setting_overrides):
    backend = sync.InMemorySyncBackend(stream_maxlen=100)
    settings = sync.SyncSettings(**setting_overrides)
    return create_app(
        engine=Dhad(),
        serve_web=False,
        sync_backend=backend,
        sync_settings=settings,
    )


def test_binary_ciphertext_is_relayed_and_not_echoed_to_sender() -> None:
    with TestClient(_app()) as client:
        with client.websocket_connect("/ws/sync/opaque") as alice:
            alice.receive_json()
            with client.websocket_connect("/ws/sync/opaque") as bob:
                bob.receive_json()
                ciphertext = b"\x00\xffauthenticated-ciphertext"
                alice.send_bytes(_client_frame(ciphertext))
                relayed = sync.unpack_server_frame(bob.receive_bytes())
                assert relayed.payload == ciphertext
                assert relayed.kind == sync.FRAME_UPDATE

                alice.send_json({"type": "ping"})
                assert alice.receive_json() == {"type": "pong"}


def test_reconnect_cursor_replays_missed_encrypted_stream_entries() -> None:
    application = _app()
    with TestClient(application) as client:
        with client.websocket_connect("/ws/sync/resume") as alice:
            alice.receive_json()
            alice.send_bytes(_client_frame(b"cipher-1"))

        with client.websocket_connect("/ws/sync/resume?cursor=0-0") as bob:
            joined = bob.receive_json()
            assert joined["type"] == "joined"
            recovered = sync.unpack_server_frame(bob.receive_bytes())
            assert recovered.payload == b"cipher-1"
            assert recovered.cursor != "0-0"


def test_websocket_recovery_pages_to_the_journal_tail() -> None:
    application = _app(recovery_limit=1)
    with TestClient(application) as client:
        with client.websocket_connect("/ws/sync/paged") as writer:
            writer.receive_json()
            for value in (b"one", b"two", b"three"):
                writer.send_bytes(_client_frame(value))

        with client.websocket_connect("/ws/sync/paged?cursor=0-0") as reader:
            reader.receive_json()
            recovered = [sync.unpack_server_frame(reader.receive_bytes()).payload for _ in range(3)]
            assert recovered == [b"one", b"two", b"three"]


def test_plaintext_json_operations_are_rejected() -> None:
    with TestClient(_app()) as client:
        with pytest.raises(WebSocketDisconnect) as closed:
            with client.websocket_connect("/ws/sync/no-plaintext") as socket:
                socket.receive_json()
                socket.send_json({"type": "op", "payload": "plaintext"})
                socket.receive_json()
        assert closed.value.code == sync.CLOSE_BAD_MESSAGE


def test_per_connection_rate_limit_closes_abusive_peer() -> None:
    with TestClient(_app(messages_per_window=2, rate_window_seconds=60)) as client:
        with pytest.raises(WebSocketDisconnect) as closed:
            with client.websocket_connect("/ws/sync/rate") as socket:
                socket.receive_json()
                socket.send_bytes(_client_frame(b"one"))
                socket.send_bytes(_client_frame(b"two"))
                socket.send_bytes(_client_frame(b"three"))
                socket.receive_json()
        assert closed.value.code == sync.CLOSE_RATE_LIMIT


def test_bounded_peer_mailbox_signals_slow_consumer_without_blocking() -> None:
    peer = sync.PeerConnection.for_test("slow", queue_size=1)
    assert peer.offer(b"first") is True
    assert peer.offer(b"second") is False


def test_websocket_honors_api_key_authentication() -> None:
    security = SecuritySettings(api_keys=("correct-horse",))
    application = create_app(
        engine=Dhad(),
        serve_web=False,
        security_settings=security,
        sync_backend=sync.InMemorySyncBackend(),
    )
    with TestClient(application) as client:
        with pytest.raises(WebSocketDisconnect) as unauthorized:
            with client.websocket_connect("/ws/sync/private"):
                pass
        assert unauthorized.value.code == sync.CLOSE_UNAUTHORIZED

        with client.websocket_connect(
            "/ws/sync/private", headers={"x-api-key": "correct-horse"}
        ) as socket:
            assert socket.receive_json()["type"] == "joined"


def test_browser_origin_is_checked_during_websocket_upgrade() -> None:
    application = create_app(
        engine=Dhad(),
        serve_web=False,
        cors_origins=["https://trusted.example"],
        sync_backend=sync.InMemorySyncBackend(),
    )
    with TestClient(application) as client:
        with pytest.raises(WebSocketDisconnect) as rejected:
            with client.websocket_connect(
                "/ws/sync/origin", headers={"origin": "https://evil.example"}
            ):
                pass
        assert rejected.value.code == sync.CLOSE_FORBIDDEN_ORIGIN

        with client.websocket_connect(
            "/ws/sync/origin", headers={"origin": "https://trusted.example"}
        ) as socket:
            assert socket.receive_json()["type"] == "joined"


def test_text_control_frames_share_the_connection_rate_budget() -> None:
    with TestClient(_app(messages_per_window=2, rate_window_seconds=60)) as client:
        with pytest.raises(WebSocketDisconnect) as closed:
            with client.websocket_connect("/ws/sync/text-rate") as socket:
                socket.receive_json()
                socket.send_json({"type": "ping"})
                assert socket.receive_json() == {"type": "pong"}
                socket.send_json({"type": "ping"})
                assert socket.receive_json() == {"type": "pong"}
                socket.send_json({"type": "ping"})
                socket.receive_json()
        assert closed.value.code == sync.CLOSE_RATE_LIMIT


def test_websocket_bearer_authentication_matches_http_authentication() -> None:
    security = SecuritySettings(api_keys=("bearer-secret",))
    application = create_app(
        engine=Dhad(),
        serve_web=False,
        security_settings=security,
        sync_backend=sync.InMemorySyncBackend(),
    )
    with TestClient(application) as client:
        with client.websocket_connect(
            "/ws/sync/bearer", headers={"authorization": "Bearer bearer-secret"}
        ) as socket:
            assert socket.receive_json()["type"] == "joined"
