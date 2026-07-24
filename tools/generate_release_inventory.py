#!/usr/bin/env python3
"""Generate a deterministic file and directory inventory for the desktop release."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

EXCLUDED_PARTS = {'.git', 'node_modules', 'target', '.desktop-build', '__pycache__', 'web_dist'}
GENERATED_OUTPUTS = {
    'reports/DESKTOP_GOLDMASTER_INVENTORY.json',
    'reports/DESKTOP_GOLDMASTER_DIRECTORY_INVENTORY.txt',
    'reports/DESKTOP_GOLDMASTER_FILE_SHA256SUMS.txt',
}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def include(root: Path, path: Path) -> bool:
    rel = path.relative_to(root)
    return (
        path.is_file()
        and not any(part in EXCLUDED_PARTS for part in rel.parts)
        and rel.as_posix() not in GENERATED_OUTPUTS
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', default='.')
    parser.add_argument('--source-base', default='dhad-v1.0-Desktop-Ultimate-v15.zip')
    args = parser.parse_args()

    root = Path(args.root).resolve()
    files = sorted((p for p in root.rglob('*') if include(root, p)), key=lambda p: p.relative_to(root).as_posix())
    entries = []
    top = defaultdict(lambda: {'files': 0, 'bytes': 0})
    extensions: Counter[str] = Counter()

    for path in files:
        rel = path.relative_to(root).as_posix()
        size = path.stat().st_size
        sha = digest(path)
        entries.append({'path': rel, 'bytes': size, 'sha256': sha})
        bucket = rel.split('/', 1)[0]
        top[bucket]['files'] += 1
        top[bucket]['bytes'] += size
        suffix = path.suffix.lower() or '[no extension]'
        extensions[suffix] += 1

    inventory = {
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'source_base': args.source_base,
        'excluded_parts': sorted(EXCLUDED_PARTS),
        'generated_outputs_excluded_from_self_hashing': sorted(GENERATED_OUTPUTS),
        'file_count': len(entries),
        'total_bytes': sum(item['bytes'] for item in entries),
        'top_level': dict(sorted(top.items())),
        'extension_counts': dict(sorted(extensions.items(), key=lambda item: (-item[1], item[0]))),
        'files': entries,
    }

    reports = root / 'reports'
    reports.mkdir(exist_ok=True)
    (reports / 'DESKTOP_GOLDMASTER_INVENTORY.json').write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'
    )

    lines = [
        'Dhad Desktop Gold Master — Directory Inventory',
        '================================================',
        f"Source base: {args.source_base}",
        f"Files inventoried: {inventory['file_count']}",
        f"Total bytes: {inventory['total_bytes']}",
        '',
        'Top-level inventory:',
    ]
    for name, values in inventory['top_level'].items():
        lines.append(f"- {name}: {values['files']} files, {values['bytes']} bytes")
    lines.extend(['', 'Extension counts:'])
    for extension, count in inventory['extension_counts'].items():
        lines.append(f'- {extension}: {count}')
    (reports / 'DESKTOP_GOLDMASTER_DIRECTORY_INVENTORY.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')

    checksum_lines = [f"{item['sha256']}  {item['path']}" for item in entries]
    (reports / 'DESKTOP_GOLDMASTER_FILE_SHA256SUMS.txt').write_text('\n'.join(checksum_lines) + '\n', encoding='utf-8')
    print(f"Inventoried {len(entries)} files ({inventory['total_bytes']} bytes).")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
