"""Fetch checksum-pinned platform tools; never check out the platform source."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import urllib.request
import zipfile

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--artifact-directory', type=Path, help='Use local artifacts with the same pinned checksums')
args = parser.parse_args()
lock = json.loads((root / 'platform.lock.json').read_text())
target = root / '.platform'
target.mkdir(exist_ok=True)
for kind in ('cli', 'module_ui', 'module_host'):
    entry = lock[kind]
    if args.artifact_directory:
        data = (args.artifact_directory / entry['path']).read_bytes()
    else:
        with urllib.request.urlopen('https://pocketrealms.ai/sdk/' + entry['path'], timeout=60) as response:
            data = response.read(32 * 1024 * 1024 + 1)
    if len(data) > 32 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != entry['sha256']:
        raise SystemExit(kind + ' artifact checksum failed')
    file = target / entry['path']
    file.write_bytes(data)
    if kind == 'cli':
        subprocess.run([sys.executable, '-m', 'pip', 'install', str(file)], check=True)
    elif kind == 'module_ui':
        subprocess.run(['npm', 'install', '--prefix', str(target / 'ui'), '--no-package-lock',
            '--no-audit', '--no-fund', '--ignore-scripts', str(file)], check=True)
    else:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for item in archive.infolist():
                destination = (target / 'host' / item.filename).resolve()
                if not destination.is_relative_to((target / 'host').resolve()):
                    raise SystemExit('Unsafe test host path')
            archive.extractall(target / 'host')
print('Installed pinned CLI, panel builder and compiled browser test host.')
