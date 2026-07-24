"""Phase 9 LSP 3.17 diagnostics, hover, and safe code-action tests."""

from __future__ import annotations

import io
from pathlib import Path

from dhad.lsp.protocol import JsonRpcStream, LineIndex, Position, Range
from dhad.lsp.server import DhadLanguageServer


def open_document(server: DhadLanguageServer, text: str, *, uri: str = "file:///doc.txt") -> str:
    server.dispatch(
        "textDocument/didOpen",
        {
            "textDocument": {
                "uri": uri,
                "languageId": "arabic",
                "version": 1,
                "text": text,
            }
        },
    )
    return uri


def test_initialize_advertises_required_lsp_capabilities():
    server = DhadLanguageServer()
    result = server.dispatch("initialize", {"capabilities": {}})
    capabilities = result["capabilities"]
    assert capabilities["textDocumentSync"]["change"] == 2
    assert capabilities["hoverProvider"] is True
    assert "quickfix" in capabilities["codeActionProvider"]["codeActionKinds"]


def test_open_publishes_spelling_and_grammar_diagnostics():
    notifications = []
    server = DhadLanguageServer(notify=notifications.append)
    open_document(server, "ذهبت الى المدرسه")
    notification = notifications[-1]
    assert notification["method"] == "textDocument/publishDiagnostics"
    diagnostics = notification["params"]["diagnostics"]
    assert [item["code"] for item in diagnostics] == ["HAMZA_ILA", "TAA_MADRASA"]
    assert diagnostics[0]["data"]["autofix"] is True
    assert diagnostics[0]["range"]["start"] == {"line": 0, "character": 5}


def test_incremental_change_republishes_clean_diagnostics():
    notifications = []
    server = DhadLanguageServer(notify=notifications.append)
    uri = open_document(server, "ذهبت الى المدرسه")
    server.dispatch(
        "textDocument/didChange",
        {
            "textDocument": {"uri": uri, "version": 2},
            "contentChanges": [{"text": "ذهبت إلى المدرسة"}],
        },
    )
    assert notifications[-1]["params"]["version"] == 2
    assert notifications[-1]["params"]["diagnostics"] == []


def test_incremental_range_change_uses_utf16_positions():
    notifications = []
    server = DhadLanguageServer(notify=notifications.append)
    uri = open_document(server, "😀 ذهبت الى السوق")
    server.dispatch(
        "textDocument/didChange",
        {
            "textDocument": {"uri": uri, "version": 2},
            "contentChanges": [
                {
                    "range": {
                        "start": {"line": 0, "character": 8},
                        "end": {"line": 0, "character": 11},
                    },
                    "text": "إلى",
                }
            ],
        },
    )
    assert server.documents.get(uri).text == "😀 ذهبت إلى السوق"
    assert notifications[-1]["params"]["diagnostics"] == []


def test_hover_exposes_morphology_and_candidate_irab():
    server = DhadLanguageServer()
    uri = open_document(server, "كتب الطالب الدرس")
    hover = server.dispatch(
        "textDocument/hover",
        {"textDocument": {"uri": uri}, "position": {"line": 0, "character": 1}},
    )
    value = hover["contents"]["value"]
    assert "اللمّة" in value and "الجذر" in value
    assert "الإعراب المرشح" in value and "ثقة" in value
    assert hover["range"]["start"] == {"line": 0, "character": 0}


def test_code_actions_expose_only_safe_autofixes():
    server = DhadLanguageServer()
    uri = open_document(server, "ذهبت الى المدرسه وفي هذا الوقت الراهن")
    actions = server.dispatch(
        "textDocument/codeAction",
        {
            "textDocument": {"uri": uri},
            "range": {
                "start": {"line": 0, "character": 0},
                "end": {"line": 0, "character": 41},
            },
            "context": {"diagnostics": []},
        },
    )
    individual = [item for item in actions if item["data"].get("rule")]
    assert {item["data"]["rule"] for item in individual} == {"HAMZA_ILA", "TAA_MADRASA"}
    assert all(item["data"]["safeAutofix"] is True for item in actions)
    assert all("الوقت الراهن" not in item["title"] for item in actions)


def test_close_clears_diagnostics():
    notifications = []
    server = DhadLanguageServer(notify=notifications.append)
    uri = open_document(server, "ذهبت الى السوق")
    server.dispatch("textDocument/didClose", {"textDocument": {"uri": uri}})
    assert notifications[-1]["params"] == {"uri": uri, "diagnostics": []}


def test_line_index_round_trip_for_utf16_and_multiline_text():
    text = "😀 ضاد\nلغة عربية"
    index = LineIndex(text)
    for offset in range(len(text) + 1):
        position = index.offset_to_position(offset)
        assert index.position_to_offset(position) == offset
    span = index.range_to_span(Range(start=Position(1, 0), end=Position(1, 3)))
    assert text[slice(*span)] == "لغة"


def test_jsonrpc_stream_round_trip():
    output = io.BytesIO()
    writer = JsonRpcStream(io.BytesIO(), output)
    message = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    writer.write_message(message)
    output.seek(0)
    reader = JsonRpcStream(output, io.BytesIO())
    assert reader.read_message() == message


def test_cli_lsp_stdio_handshake(tmp_path):
    import json
    import os
    import subprocess
    import sys

    def frame(message):
        payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
        return f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii") + payload

    request = b"".join(
        [
            frame({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
            frame({"jsonrpc": "2.0", "id": 2, "method": "shutdown", "params": {}}),
            frame({"jsonrpc": "2.0", "method": "exit", "params": {}}),
        ]
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(Path(__file__).parents[1] / "src"), str(Path(__file__).parents[1])]
    )
    result = subprocess.run(
        [sys.executable, "-m", "dhad.cli", "lsp"],
        input=request,
        capture_output=True,
        timeout=60,
        env=environment,
        check=False,
    )
    assert result.returncode == 0
    assert b'"hoverProvider":true' in result.stdout
    assert result.stderr == b""
