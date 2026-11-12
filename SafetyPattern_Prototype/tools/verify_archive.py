"""Check saved archive evidence without importing or running the prototype."""
from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from statistics import median, quantiles

ROOT = Path(__file__).resolve().parents[1]
IGNORED = {'.git', '.venv', '__pycache__', '.pytest_cache', '.idea', '.vscode', 'reproduced', 'node_modules'}
PHASES = ['context_extraction_ms', 'obligation_generation_ms', 'context_check_ms', 'obligation_check_ms', 'combination_aggregation_ms', 'failure_analysis_ms', 'total_verification_ms']


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256(file: Path) -> str:
    return hashlib.sha256(file.read_bytes()).hexdigest()


def files() -> list[Path]:
    return sorted((p for p in ROOT.rglob('*') if p.is_file()
                   and not any(part in IGNORED for part in p.relative_to(ROOT).parts)
                   and not p.name.endswith('.xlsx.inspect.ndjson')
                   and p != ROOT / 'checksums.sha256'), key=lambda p: p.relative_to(ROOT).as_posix())


def safe_path(name: str) -> Path:
    path = (ROOT / name).resolve()
    require(path.is_relative_to(ROOT), f'Path escapes archive: {name}')
    return path


def write_checksums() -> None:
    text = ''.join(f'{sha256(p)}  {p.relative_to(ROOT).as_posix()}\n' for p in files())
    (ROOT / 'checksums.sha256').write_text(text, encoding='utf-8', newline='\n')


def check_hashes() -> int:
    listed = {}
    for line in (ROOT / 'checksums.sha256').read_text(encoding='utf-8').splitlines():
        digest, name = line.split('  ', 1)
        require(bool(re.fullmatch('[0-9a-f]{64}', digest)), f'Invalid hash: {name}')
        require(name not in listed, f'Duplicate hash entry: {name}')
        target = safe_path(name)
        require(target.is_file() and sha256(target) == digest, f'Checksum mismatch: {name}')
        listed[name] = digest
    actual = {p.relative_to(ROOT).as_posix() for p in files()}
    require(actual == set(listed), 'File inventory differs; inspect changes before explicitly refreshing checksums')
    manifest = json.loads((ROOT / 'provenance/source-manifest.json').read_text(encoding='utf-8'))
    for item in manifest['files']:
        require(sha256(safe_path(item['archive_path'])) == item['archive_sha256'], f'Source-copy mismatch: {item["archive_path"]}')
        if item['transformation'] == 'byte_copy':
            require(item['archive_sha256'] == item['source_sha256'], f'Byte-copy source hash mismatch: {item["archive_path"]}')
    return len(listed)


def key(row: dict) -> tuple:
    return int(row['K']), row['variant'], row['resource_configuration']


def check_experiment(folder: str, count: int, group_count: int) -> dict:
    directory = ROOT / 'results' / folder
    payload = json.loads((directory / 'scalability_results.json').read_text(encoding='utf-8'))
    configuration = json.loads((directory / 'scalability_configuration.json').read_text(encoding='utf-8'))
    require(payload['configuration'] == configuration['configuration'], f'{folder}: configuration mismatch')
    raw = payload['raw_runs']
    require(len(raw) == count and len(payload['summary']) == group_count, f'{folder}: record counts')
    require(all(r['variant'] == 'valid' for r in raw), f'{folder}: unexpected variant')
    allowed = set(payload['configuration']['resource_configurations'])
    require(all(r['resource_configuration'] in allowed for r in raw), f'{folder}: unexpected resource configuration')
    repetitions = payload['configuration']['repetitions']
    require(len({key(r) + (r['repetition'],) for r in raw}) == count, f'{folder}: duplicate run identifiers')
    for row in payload['summary']:
        group = [r for r in raw if key(r) == key(row)]
        require(len(group) == repetitions, f'{folder}: missing group records')
        require(sorted(r['repetition'] for r in group) == list(range(1, repetitions+1)), f'{folder}: repetition IDs')
        for field in PHASES:
            values = [r[field] for r in group if r.get(field) is not None]
            if not values:
                continue
            q1, _, q3 = quantiles(values, n=4, method='inclusive')
            for stat, expected in [('median', median(values)), ('q1', q1), ('q3', q3)]:
                require(abs(row[f'{field}_{stat}_ms'] - expected) < 1e-8, f'{folder}: {field} {stat} differs from raw runs')
    with (directory / 'scalability_summary.csv').open(encoding='utf-8-sig', newline='') as f:
        csv_summary = {key(row): row for row in csv.DictReader(f)}
    require(len(csv_summary) == group_count, f'{folder}: CSV summary row count')
    for row in payload['summary']:
        for name, value in row.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                require(float(csv_summary[key(row)][name]) == value, f'{folder}: CSV/JSON summary mismatch: {name}')
    with (directory / 'scalability_results.csv').open(encoding='utf-8-sig', newline='') as f:
        csv_raw = {key(row) + (int(row['repetition']),): row for row in csv.DictReader(f)}
    require(len(csv_raw) == count, f'{folder}: CSV raw row count')
    for row in raw:
        counterpart = csv_raw[key(row) + (row['repetition'],)]
        for name, value in row.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                require(float(counterpart[name]) == value, f'{folder}: CSV/JSON raw mismatch: {name}')
    warmups = [json.loads(line) for line in (directory / 'scalability_warmup.jsonl').read_text(encoding='utf-8').splitlines() if line]
    require(len(warmups) == group_count * payload['configuration']['warmup'], f'{folder}: warmup count')
    require(payload['environment']['source_sha256'] == configuration['environment']['source_sha256'], f'{folder}: source lists differ')
    for name, expected in payload['environment']['source_sha256'].items():
        require(sha256(safe_path(name)) == expected, f'{folder}: historical execution-source mismatch: {name}')
    return {'formal_runs': len(raw), 'summary_groups': len(payload['summary']), 'warmup_runs': len(warmups)}


def check_inputs() -> int:
    inputs = sorted((ROOT / 'data').glob('*.yaml'))
    parents = {}
    for file in inputs:
        match = re.search(r'^extends:\s*([^\r\n#]+)', file.read_text(encoding='utf-8'), re.MULTILINE)
        if match:
            parent = match.group(1).strip().strip('\"\'')
            require((file.parent / parent).is_file(), f'Missing YAML parent: {parent}')
            parents[file.name] = parent
    for name in parents:
        seen = set()
        while name in parents:
            require(name not in seen, 'Cyclic YAML inheritance')
            seen.add(name)
            name = parents[name]
    for file in list((ROOT / 'src').glob('*.py')) + list(ROOT.glob('run_*.py')):
        ast.parse(file.read_text(encoding='utf-8-sig'), filename=file.name)
    return len(inputs)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write-checksums', action='store_true', help='Explicitly replace this archive checksum list after reviewing additions/changes')
    args = parser.parse_args()
    if args.write_checksums:
        write_checksums()
    report = {'files_checked': check_hashes(), 'yaml_inputs': check_inputs(),
              'scalability_20261110': check_experiment('scalability-20261110', 140, 14),
              'cross_unit_k2': check_experiment('cross-unit-k2', 20, 2),
              'experiments_executed': False}
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
