"""Verify frozen ZIP bytes against immutable public Git blobs; stdlib only, read-only."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import zipfile


def verify(repo, package, record):
    sha = lambda data: hashlib.sha256(data).hexdigest()
    if sha(Path(package).read_bytes()) != record['package_sha256']:
        raise ValueError('Frozen ZIP SHA256 mismatch')
    commit = record['public_source_commit']
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('Source must be a full immutable Git commit')
    prefix = record['zip_prefix']
    source = record['public_source_path']
    expected = record['file_sha256']
    if len(expected) != record['file_count'] or not expected:
        raise ValueError('Invalid file count')
    with zipfile.ZipFile(package) as archive:
        names = [n for n in archive.namelist() if not n.endswith('/')]
        if len(names) != len(set(names)):
            raise ValueError('Duplicate ZIP entries')
        if set(names) != {prefix + rel for rel in expected}:
            raise ValueError('ZIP entries differ from provenance allowlist')
        for rel, digest in expected.items():
            path = PurePosixPath(rel)
            if path.is_absolute() or '..' in path.parts or '\\' in rel or ':' in rel:
                raise ValueError('Unsafe relative path')
            raw = archive.read(prefix + rel)
            blob = subprocess.check_output(['git', 'show', f'{commit}:{source}/{rel}'], cwd=repo)
            if raw != blob or sha(raw) != digest:
                raise ValueError(f'Byte mismatch: {rel}')
        if archive.read(prefix + 'VERSION').decode().strip() != record['skill_version']:
            raise ValueError('Version mismatch')
        manifest = json.loads(archive.read(prefix + 'AIX_SKILL_V0_1_RELEASE_MANIFEST.json'))
        if manifest['build_id'] != record['build_id']:
            raise ValueError('Build ID mismatch')
        if manifest['source_commit'] != record['protocol_build_input_commit']:
            raise ValueError('Build input mismatch')
    return {'status': 'PASS', 'source_commit': commit, 'files_matched': len(expected),
            'build_id': record['build_id'], 'package_sha256': record['package_sha256']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zip', required=True, type=Path)
    parser.add_argument('--record', type=Path, default=Path('V0_2_3_PROVENANCE.json'),
                        help='External provenance record; relative paths resolve from repository root')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        record_path = args.record if args.record.is_absolute() else root / args.record
        print(json.dumps(verify(root, args.zip, json.loads(record_path.read_text(encoding='utf-8'))), indent=2))
    except (ValueError, KeyError, OSError, zipfile.BadZipFile, subprocess.CalledProcessError) as exc:
        parser.exit(1, f'FAIL: {exc}\n')
