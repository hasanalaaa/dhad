"""Cross-runtime proof that Dhad's Yrs updates are byte-compatible with Yjs."""

from __future__ import annotations

import base64
import json
from pathlib import Path
import subprocess

from dhad.crdt import CrdtDocument

ROOT = Path(__file__).resolve().parents[1]
WEB_DEMO = ROOT / "web_demo"


def _node(script: str, payload: dict[str, str]) -> dict[str, str]:
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script, json.dumps(payload)],
        cwd=WEB_DEMO,
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout)


def test_python_yrs_update_is_applied_by_yjs() -> None:
    document = CrdtDocument("python")
    update = document.local_insert(0, "نص من Rust/Yrs")
    result = _node(
        """
        import * as Y from 'yjs';
        const input = JSON.parse(process.argv[1]);
        const doc = new Y.Doc();
        Y.applyUpdate(doc, Buffer.from(input.update, 'base64'));
        process.stdout.write(JSON.stringify({text: doc.getText('text').toString()}));
        """,
        {"update": base64.b64encode(update).decode("ascii")},
    )
    assert result["text"] == document.text


def test_yjs_update_is_applied_by_python_yrs() -> None:
    result = _node(
        """
        import * as Y from 'yjs';
        const doc = new Y.Doc();
        doc.getText('text').insert(0, 'تحديث من Yjs');
        process.stdout.write(JSON.stringify({
          update: Buffer.from(Y.encodeStateAsUpdate(doc)).toString('base64')
        }));
        """,
        {},
    )
    document = CrdtDocument("python")
    document.apply(base64.b64decode(result["update"]))
    assert document.text == "تحديث من Yjs"
