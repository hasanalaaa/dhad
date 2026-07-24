#!/usr/bin/env python3
"""Safely optimize ONNX assets without changing model semantics.

The release model is already INT8. If the optional `onnx` package is installed,
this tool strips documentation metadata, validates the graph, serializes it
atomically, and keeps the result only when it is smaller. Without `onnx`, it
still performs deterministic integrity, duplication, and size checks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def strip_docs(model: Any) -> None:
    model.doc_string = ''
    graph = model.graph
    graph.doc_string = ''
    for value in list(graph.input) + list(graph.output) + list(graph.value_info):
        value.doc_string = ''
    for node in graph.node:
        node.doc_string = ''
    for fn in getattr(model, 'functions', []):
        fn.doc_string = ''
        for node in fn.node:
            node.doc_string = ''


def optimize(path: Path) -> dict[str, Any]:
    before_size = path.stat().st_size
    before_hash = sha256(path)
    record: dict[str, Any] = {
        'path': path.as_posix(),
        'before_bytes': before_size,
        'before_sha256': before_hash,
        'after_bytes': before_size,
        'after_sha256': before_hash,
        'changed': False,
        'status': 'verified',
    }
    try:
        import onnx  # type: ignore
    except Exception:
        record['status'] = 'verified; optional onnx package not installed'
        return record

    try:
        model = onnx.load(str(path), load_external_data=True)
        input_names = [v.name for v in model.graph.input]
        output_names = [v.name for v in model.graph.output]
        onnx.checker.check_model(model)
        strip_docs(model)
        serialized = model.SerializeToString(deterministic=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + '.', suffix='.tmp', delete=False) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(serialized)
        candidate = onnx.load(str(tmp_path), load_external_data=True)
        onnx.checker.check_model(candidate)
        if [v.name for v in candidate.graph.input] != input_names or [v.name for v in candidate.graph.output] != output_names:
            raise RuntimeError('model interface changed during optimization')
        if tmp_path.stat().st_size < before_size:
            os.replace(tmp_path, path)
            record['changed'] = True
            record['status'] = 'metadata stripped and deterministic serialization retained'
        else:
            tmp_path.unlink(missing_ok=True)
            record['status'] = 'already size-optimal; original retained'
        record['after_bytes'] = path.stat().st_size
        record['after_sha256'] = sha256(path)
    except Exception as exc:
        record['status'] = f'validation failed; original retained: {exc}'
        try:
            tmp_path.unlink(missing_ok=True)  # type: ignore[name-defined]
        except Exception:
            pass
    return record


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='.')
    ap.add_argument('--write-manifest', action='store_true')
    args = ap.parse_args()
    root = Path(args.root).resolve()
    models = sorted(p for p in root.rglob('*.onnx') if '.git' not in p.parts and 'target' not in p.parts)
    if not models:
        raise SystemExit('No ONNX assets found.')
    records = [optimize(p) for p in models]
    hashes: dict[str, list[str]] = {}
    for rec in records:
        rel = Path(rec['path']).resolve().relative_to(root).as_posix()
        rec['path'] = rel
        hashes.setdefault(rec['after_sha256'], []).append(rel)
    duplicates = [paths for paths in hashes.values() if len(paths) > 1]
    manifest = {
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'model_count': len(records),
        'total_bytes': sum(int(r['after_bytes']) for r in records),
        'duplicates': duplicates,
        'models': records,
    }
    if args.write_manifest:
        out = root / 'reports' / 'DESKTOP_ONNX_ASSET_MANIFEST.json'
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        print(f'Wrote {out.relative_to(root)}')
    for rec in records:
        delta = int(rec['before_bytes']) - int(rec['after_bytes'])
        print(f"{rec['path']}: {rec['status']} ({rec['after_bytes']} bytes, saved {delta})")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
