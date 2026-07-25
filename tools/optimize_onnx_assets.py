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
from typing import Any, Iterable


EXCLUDED_SCAN_DIRS = {
    ".git", ".desktop-build", ".audit-venv", ".ci-venv", ".venv", "venv",
    "node_modules", "target", "__pycache__", ".pytest_cache",
    ".ruff_cache", ".mypy_cache",
    # web_dist is a generated copy of web_demo. Auditing it doubles the work on a
    # 135 MB model and, worse, would let --optimize rewrite the staged copy so it
    # no longer matches the integrity contract that produced it.
    "web_dist",
}


def discover_models(root: Path, model_roots: Iterable[Path] | None = None) -> list[Path]:
    """Return only first-party ONNX assets, never models installed in build tooling.

    The local build venv contains hundreds of ONNX backend fixtures. Scanning those
    is both incorrect and extremely noisy, so every generated/dependency directory
    is pruned regardless of where the virtual environment lives.
    """
    candidates: list[Path] = []
    search_roots = list(model_roots or [root])
    for search_root in search_roots:
        if not search_root.exists():
            continue
        for path in search_root.rglob("*.onnx"):
            try:
                relative = path.resolve().relative_to(root)
            except ValueError:
                continue
            if any(part in EXCLUDED_SCAN_DIRS for part in relative.parts):
                continue
            if path.is_file():
                candidates.append(path.resolve())
    return sorted(set(candidates))


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


def optimize(path: Path, *, rewrite: bool = False) -> dict[str, Any]:
    """Validate an ONNX asset, and rewrite it only when explicitly asked to.

    Rewriting is opt-in because these models are versioned release inputs whose
    SHA-256 is pinned in ``web_demo/models/student-manifest.json`` and
    ``SHA256SUMS.txt``. A validation step that silently mutates them turns a green
    checkout into a build that fails several steps later — and only on machines
    where the optional ``onnx`` package happens to be installed, which is exactly
    the local/CI divergence this pipeline must not have. Candidate serializations
    are written to a temporary directory outside the repository so an interrupted
    run cannot leave a ``.tmp`` file inside the tracked tree either.
    """
    before_size = path.stat().st_size
    before_hash = sha256(path)
    record: dict[str, Any] = {
        'path': path.as_posix(),
        'before_bytes': before_size,
        'before_sha256': before_hash,
        'after_bytes': before_size,
        'after_sha256': before_hash,
        'changed': False,
        'rewrite_requested': rewrite,
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
        with tempfile.TemporaryDirectory(prefix='dhad-onnx-') as scratch:
            tmp_path = Path(scratch) / (path.name + '.candidate')
            tmp_path.write_bytes(serialized)
            candidate = onnx.load(str(tmp_path), load_external_data=True)
            onnx.checker.check_model(candidate)
            if [v.name for v in candidate.graph.input] != input_names or [v.name for v in candidate.graph.output] != output_names:
                raise RuntimeError('model interface changed during optimization')
            candidate_size = tmp_path.stat().st_size
            record['candidate_bytes'] = candidate_size
            if candidate_size >= before_size:
                record['status'] = 'graph validated; already size-optimal'
            elif not rewrite:
                record['status'] = (
                    f'graph validated; {before_size - candidate_size} redundant metadata byte(s) '
                    'available, rerun with --optimize to rewrite the versioned asset'
                )
            else:
                os.replace(tmp_path, path)
                record['changed'] = True
                record['status'] = 'metadata stripped and deterministic serialization retained'
        record['after_bytes'] = path.stat().st_size
        record['after_sha256'] = sha256(path)
    except Exception as exc:
        record['status'] = f'validation failed; original retained: {exc}'
    return record


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='.')
    ap.add_argument('--write-manifest', action='store_true')
    ap.add_argument(
        '--optimize',
        action='store_true',
        help='Rewrite versioned ONNX assets in place when metadata stripping shrinks them. '
        'Off by default: release pipelines must verify, never mutate, pinned assets. '
        'After using it, refresh SHA256SUMS.txt and web_demo/models/student-manifest.json.',
    )
    ap.add_argument('--model-root', action='append', default=[], help='Optional first-party model directory, relative to --root; may be repeated.')
    args = ap.parse_args()
    root = Path(args.root).resolve()
    requested_roots = [(root / item).resolve() for item in args.model_root]
    models = discover_models(root, requested_roots or None)
    if not models:
        raise SystemExit('No ONNX assets found.')
    records = [optimize(p, rewrite=args.optimize) for p in models]
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
