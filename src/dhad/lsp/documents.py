"""In-memory LSP text document store with full and incremental updates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .protocol import LineIndex, Range


@dataclass(slots=True)
class TextDocument:
    uri: str
    text: str
    version: int | None
    language_id: str = "arabic"

    def apply_changes(self, changes: list[dict[str, Any]], version: int | None) -> None:
        for change in changes:
            replacement = str(change.get("text", ""))
            range_payload = change.get("range")
            if range_payload is None:
                self.text = replacement
                continue
            line_index = LineIndex(self.text)
            start, end = line_index.range_to_span(Range.from_mapping(range_payload))
            self.text = self.text[:start] + replacement + self.text[end:]
        self.version = version


class TextDocumentStore:
    def __init__(self) -> None:
        self._documents: dict[str, TextDocument] = {}

    def open(self, payload: dict[str, Any]) -> TextDocument:
        uri = str(payload["uri"])
        document = TextDocument(
            uri=uri,
            text=str(payload.get("text", "")),
            version=payload.get("version"),
            language_id=str(payload.get("languageId", "arabic")),
        )
        self._documents[uri] = document
        return document

    def change(
        self,
        uri: str,
        changes: list[dict[str, Any]],
        version: int | None,
    ) -> TextDocument:
        document = self.get(uri)
        document.apply_changes(changes, version)
        return document

    def close(self, uri: str) -> TextDocument | None:
        return self._documents.pop(uri, None)

    def get(self, uri: str) -> TextDocument:
        try:
            return self._documents[uri]
        except KeyError as exc:
            raise KeyError(f"Unknown text document: {uri}") from exc
