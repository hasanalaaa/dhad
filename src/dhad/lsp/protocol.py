"""LSP 3.17 position, range, and JSON-RPC framing primitives."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, BinaryIO


def _utf16_units(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


@dataclass(frozen=True, slots=True)
class Position:
    line: int
    character: int

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "Position":
        line = int(payload.get("line", -1))
        character = int(payload.get("character", -1))
        if line < 0 or character < 0:
            raise ValueError("LSP positions must be non-negative")
        return cls(line=line, character=character)

    def as_dict(self) -> dict[str, int]:
        return {"line": self.line, "character": self.character}


@dataclass(frozen=True, slots=True)
class Range:
    start: Position
    end: Position

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "Range":
        return cls(
            start=Position.from_mapping(payload.get("start", {})),
            end=Position.from_mapping(payload.get("end", {})),
        )

    def as_dict(self) -> dict[str, dict[str, int]]:
        return {"start": self.start.as_dict(), "end": self.end.as_dict()}


class LineIndex:
    """Convert Python offsets to/from LSP UTF-16 positions exactly."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.starts = [0]
        for index, character in enumerate(text):
            if character == "\n":
                self.starts.append(index + 1)

    def position_to_offset(self, position: Position) -> int:
        if position.line >= len(self.starts):
            return len(self.text)
        line_start = self.starts[position.line]
        line_end = (
            self.starts[position.line + 1] - 1
            if position.line + 1 < len(self.starts)
            else len(self.text)
        )
        segment = self.text[line_start:line_end]
        units = 0
        for index, character in enumerate(segment):
            width = _utf16_units(character)
            if units + width > position.character:
                return line_start + index
            units += width
            if units == position.character:
                return line_start + index + 1
        return line_end

    def offset_to_position(self, offset: int) -> Position:
        offset = min(max(offset, 0), len(self.text))
        line = 0
        low, high = 0, len(self.starts)
        while low < high:
            middle = (low + high) // 2
            if self.starts[middle] <= offset:
                line = middle
                low = middle + 1
            else:
                high = middle
        line_start = self.starts[line]
        return Position(line=line, character=_utf16_units(self.text[line_start:offset]))

    def span_to_range(self, offset: int, length: int) -> Range:
        return Range(
            start=self.offset_to_position(offset),
            end=self.offset_to_position(offset + length),
        )

    def range_to_span(self, value: Range) -> tuple[int, int]:
        start = self.position_to_offset(value.start)
        end = self.position_to_offset(value.end)
        return start, max(start, end)


class JsonRpcStream:
    """Read and write Content-Length-framed JSON-RPC messages."""

    def __init__(self, reader: BinaryIO, writer: BinaryIO) -> None:
        self.reader = reader
        self.writer = writer

    def read_message(self) -> dict[str, Any] | None:
        headers: dict[str, str] = {}
        while True:
            line = self.reader.readline()
            if not line:
                return None
            if line in {b"\r\n", b"\n"}:
                break
            decoded = line.decode("ascii", errors="strict").strip()
            if ":" not in decoded:
                raise ValueError("Malformed JSON-RPC header")
            name, value = decoded.split(":", 1)
            headers[name.lower().strip()] = value.strip()
        if "content-length" not in headers:
            raise ValueError("Missing Content-Length header")
        length = int(headers["content-length"])
        if length < 0 or length > 64 * 1024 * 1024:
            raise ValueError("Invalid JSON-RPC payload size")
        payload = self.reader.read(length)
        if len(payload) != length:
            raise EOFError("Truncated JSON-RPC payload")
        message = json.loads(payload.decode("utf-8"))
        if not isinstance(message, dict):
            raise ValueError("JSON-RPC message must be an object")
        return message

    def write_message(self, message: dict[str, Any]) -> None:
        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.writer.write(f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii"))
        self.writer.write(payload)
        self.writer.flush()
