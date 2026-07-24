"""Dependency-free LSP 3.17 server for Arabic diagnostics and analysis."""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any

from dhad import Dhad, Match, __version__

from .documents import TextDocument, TextDocumentStore
from .protocol import JsonRpcStream, LineIndex, Position, Range

NotificationSink = Callable[[dict[str, Any]], None]

_DIAGNOSTIC_SEVERITY = {"error": 1, "warning": 2, "hint": 4}


class DhadLanguageServer:
    """Stateful LSP service sharing the production Dhad engine."""

    def __init__(
        self,
        engine: Dhad | None = None,
        *,
        notify: NotificationSink | None = None,
    ) -> None:
        self.engine = engine or Dhad()
        self.documents = TextDocumentStore()
        self.notify = notify or (lambda _message: None)
        self.shutdown_requested = False

    @staticmethod
    def capabilities() -> dict[str, Any]:
        return {
            "textDocumentSync": {
                "openClose": True,
                "change": 2,
                "save": {"includeText": True},
            },
            "hoverProvider": True,
            "codeActionProvider": {
                "codeActionKinds": ["quickfix"],
                "resolveProvider": False,
            },
            "serverInfo": {"name": "Dhad LSP", "version": __version__},
        }

    def _diagnostic(self, text: str, match: Match) -> dict[str, Any]:
        value = {
            "range": LineIndex(text).span_to_range(match.offset, match.length).as_dict(),
            "severity": _DIAGNOSTIC_SEVERITY[match.severity],
            "code": match.rule_id,
            "codeDescription": {
                "href": f"https://github.com/dhad-project/dhad#rule-{match.rule_id}"
            },
            "source": "dhad",
            "message": match.message,
            "data": {
                "category": match.category,
                "replacements": list(match.replacements),
                "autofix": match.autofix,
                "confidence": match.confidence,
                "explanation": match.explanation,
            },
        }
        if match.tags:
            value["tags"] = [1] if "deprecated" in match.tags else []
        return value

    def diagnostics(self, document: TextDocument) -> list[dict[str, Any]]:
        return [self._diagnostic(document.text, item) for item in self.engine.check(document.text)]

    def publish_diagnostics(self, document: TextDocument) -> dict[str, Any]:
        notification = {
            "jsonrpc": "2.0",
            "method": "textDocument/publishDiagnostics",
            "params": {
                "uri": document.uri,
                "version": document.version,
                "diagnostics": self.diagnostics(document),
            },
        }
        self.notify(notification)
        return notification

    def _hover(self, params: dict[str, Any]) -> dict[str, Any] | None:
        uri = str(params["textDocument"]["uri"])
        document = self.documents.get(uri)
        position = Position.from_mapping(params["position"])
        offset = LineIndex(document.text).position_to_offset(position)
        parsed = self.engine.parse(document.text)
        for sentence in parsed.sentences:
            for index, token in enumerate(sentence.tokens):
                if token.start <= offset <= token.end:
                    analysis = token.analysis
                    irab = next((item for item in sentence.irab if item.token_index == index), None)
                    lines = [f"### {token.text}", ""]
                    if analysis is None:
                        lines.append("لا توجد قراءة صرفية موثوقة.")
                    else:
                        lines.extend(
                            [
                                f"- **اللمّة:** {analysis.lemma}",
                                f"- **الجذر:** {analysis.root or '—'}",
                                f"- **الوزن:** {analysis.pattern or '—'}",
                                f"- **النوع:** {analysis.pos}",
                                f"- **ثقة الصرف:** {token.confidence:.1%}",
                            ]
                        )
                    if irab is not None:
                        lines.extend(
                            [
                                "",
                                f"- **الإعراب المرشح:** {irab.role}",
                                f"- **الحالة/المزاج:** {irab.case_or_mood}",
                                f"- **العلامة:** {irab.marker or '—'}",
                                f"- **ثقة الإعراب:** {irab.confidence:.1%}",
                                f"- {irab.explanation}",
                            ]
                        )
                    return {
                        "contents": {"kind": "markdown", "value": "\n".join(lines)},
                        "range": LineIndex(document.text)
                        .span_to_range(token.start, token.end - token.start)
                        .as_dict(),
                    }
        return None

    def _code_actions(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        uri = str(params["textDocument"]["uri"])
        document = self.documents.get(uri)
        requested = Range.from_mapping(params["range"])
        start, end = LineIndex(document.text).range_to_span(requested)
        safe_matches = [
            item
            for item in self.engine.check(document.text)
            if item.autofix
            and item.replacements
            and item.offset < max(end, start + 1)
            and start < item.end
        ]
        index = LineIndex(document.text)
        actions: list[dict[str, Any]] = []
        for match in safe_matches:
            edit = {
                "range": index.span_to_range(match.offset, match.length).as_dict(),
                "newText": match.replacements[0],
            }
            actions.append(
                {
                    "title": f"ضاد: {match.replacements[0]}",
                    "kind": "quickfix",
                    "diagnostics": [self._diagnostic(document.text, match)],
                    "isPreferred": True,
                    "edit": {"changes": {uri: [edit]}},
                    "data": {"rule": match.rule_id, "safeAutofix": True},
                }
            )
        if len(safe_matches) > 1:
            edits = [
                {
                    "range": index.span_to_range(item.offset, item.length).as_dict(),
                    "newText": item.replacements[0],
                }
                for item in reversed(safe_matches)
            ]
            actions.append(
                {
                    "title": "ضاد: تطبيق جميع التصحيحات الآمنة في النطاق",
                    "kind": "quickfix",
                    "isPreferred": False,
                    "edit": {"changes": {uri: edits}},
                    "data": {"safeAutofix": True, "count": len(edits)},
                }
            )
        return actions

    def dispatch(self, method: str, params: dict[str, Any] | None = None) -> Any:
        params = params or {}
        if method == "initialize":
            return {
                "capabilities": self.capabilities(),
                "serverInfo": self.capabilities()["serverInfo"],
            }
        if method == "initialized":
            return None
        if method == "shutdown":
            self.shutdown_requested = True
            return None
        if method == "exit":
            return None
        if method == "textDocument/didOpen":
            document = self.documents.open(params["textDocument"])
            self.publish_diagnostics(document)
            return None
        if method == "textDocument/didChange":
            payload = params["textDocument"]
            document = self.documents.change(
                str(payload["uri"]),
                list(params.get("contentChanges", [])),
                payload.get("version"),
            )
            self.publish_diagnostics(document)
            return None
        if method == "textDocument/didSave":
            payload = params["textDocument"]
            document = self.documents.get(str(payload["uri"]))
            if "text" in params:
                document.text = str(params["text"])
            self.publish_diagnostics(document)
            return None
        if method == "textDocument/didClose":
            uri = str(params["textDocument"]["uri"])
            document = self.documents.close(uri)
            notification = {
                "jsonrpc": "2.0",
                "method": "textDocument/publishDiagnostics",
                "params": {"uri": uri, "diagnostics": []},
            }
            if document is not None:
                self.notify(notification)
            return None
        if method == "textDocument/hover":
            return self._hover(params)
        if method == "textDocument/codeAction":
            return self._code_actions(params)
        raise KeyError(f"Unsupported LSP method: {method}")


def serve_stdio() -> int:
    """Run the LSP server over stdin/stdout using JSON-RPC 2.0 framing."""

    stream = JsonRpcStream(sys.stdin.buffer, sys.stdout.buffer)
    server = DhadLanguageServer(notify=stream.write_message)
    exit_code = 0
    while True:
        try:
            message = stream.read_message()
            if message is None:
                break
            method = message.get("method")
            request_id = message.get("id")
            if not isinstance(method, str):
                if request_id is not None:
                    stream.write_message(
                        {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "error": {"code": -32600, "message": "Invalid Request"},
                        }
                    )
                continue
            if method == "exit":
                exit_code = 0 if server.shutdown_requested else 1
                break
            try:
                result = server.dispatch(method, message.get("params"))
            except KeyError as exc:
                if request_id is not None:
                    stream.write_message(
                        {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "error": {"code": -32601, "message": str(exc)},
                        }
                    )
                continue
            except (TypeError, ValueError) as exc:
                if request_id is not None:
                    stream.write_message(
                        {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "error": {"code": -32602, "message": str(exc)},
                        }
                    )
                continue
            except Exception as exc:  # defensive protocol boundary
                if request_id is not None:
                    stream.write_message(
                        {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "error": {"code": -32603, "message": f"Internal error: {exc}"},
                        }
                    )
                continue
            if request_id is not None:
                stream.write_message({"jsonrpc": "2.0", "id": request_id, "result": result})
        except (EOFError, UnicodeError, ValueError) as exc:
            stream.write_message(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {exc}"},
                }
            )
    return exit_code


def main() -> None:
    raise SystemExit(serve_stdio())


if __name__ == "__main__":
    main()
