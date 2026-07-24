"""Synthetic mailbox-fanout benchmark for the vMAX Phase 4 sync hub.

This deliberately excludes network and Redis latency. It measures the hot
server operation that must remain non-blocking: packing one opaque ciphertext
frame and enqueueing it independently to 1,999 peer mailboxes.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dhad.sync import (  # noqa: E402
    FRAME_UPDATE,
    ClientFrame,
    InMemorySyncBackend,
    SyncHub,
    SyncSettings,
)


class _Socket:
    async def close(self, *, code: int) -> None:
        del code


async def benchmark(connections: int = 2_000, iterations: int = 30) -> dict[str, object]:
    settings = SyncSettings(
        max_peers_per_doc=connections,
        outgoing_queue_size=2,
        recovery_limit=10,
    )
    hub = SyncHub(InMemorySyncBackend(), settings=settings, node_id="benchmark")
    peers = []
    for _ in range(connections):
        joined = await hub.join("benchmark", _Socket(), after_cursor=None)
        if joined is None:
            raise RuntimeError("Benchmark room filled before the configured limit")
        peers.append(joined.peer)

    samples = []
    payload = b"x" * 1_024
    for _ in range(iterations):
        started = time.perf_counter_ns()
        await hub.publish(
            "benchmark",
            peers[0].client_id,
            ClientFrame(FRAME_UPDATE, payload),
        )
        samples.append((time.perf_counter_ns() - started) / 1_000_000)
        for peer in peers[1:]:
            peer.queue.get_nowait()

    await hub.close()
    ordered = sorted(samples)
    return {
        "connections": connections,
        "recipients_per_publish": connections - 1,
        "payload_bytes": len(payload),
        "iterations": iterations,
        "fanout_ms_p50": statistics.median(ordered),
        "fanout_ms_p95": ordered[max(0, int(len(ordered) * 0.95) - 1)],
        "scope": "in-process bounded-mailbox enqueue; excludes sockets, Redis, and crypto",
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(benchmark()), indent=2))
