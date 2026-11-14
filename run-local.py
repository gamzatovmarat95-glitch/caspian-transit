from pathlib import Path
import argparse
import subprocess
import sys
import time
import webbrowser
from urllib.request import build_opener, ProxyHandler
import json
import os
sys.dont_write_bytecode = True
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
from caspian.runtime import installation_id
root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('--no-open', action='store_true')
parser.add_argument('--check', action='store_true')
parser.add_argument(
    '--port',
    type=int,
    default=4410,
)
args = parser.parse_args()
if not 1024 <= args.port <= 65535:
    raise SystemExit('Choose an unprivileged port between1024and65535.')
try:
    import django
except ImportError:
    raise SystemExit('Django is not installed. Run INSTALL.cmd first.')
subprocess.run(
    [
        sys.executable,
        str(root / 'manage.py'),
        'check',
    ],
    cwd=root,
    check=True,
)
subprocess.run(
    [
        sys.executable,
        str(root / 'manage.py'),
        'migrate',
        '--noinput',
    ],
    cwd=root,
    check=True,
)
if args.check:
    raise SystemExit(0)
base = f'http://localhost:{args.port}'
entry = base + '/'
client = build_opener(ProxyHandler({}))
expected_instance = installation_id(root, os.environ.get('CASPIAN_DB', str(root / '.runtime/caspian.sqlite3')))


def ready():
    try:
        with client.open(base + '/api/health', timeout=1) as r:
            value = json.load(r)
        return (
            value.get('app') == 'caspian-transit'
            and value.get('framework') == 'Django'
            and value.get('instance') == expected_instance
        )
    except (OSError, ValueError):
        return False
if ready():
    print('Django Caspian Transit already running: ' + entry)
    if not args.no_open:
        webbrowser.open(entry)
    raise SystemExit(0)
try:
    with client.open(base + '/api/health', timeout=1) as reply:
        other = json.load(reply)
    if other.get('app') == 'caspian-transit':
        raise SystemExit(f'Port {args.port} belongs to another or older Caspian Transit instance. Stop it or use --port {args.port + 1}.')
except (OSError, ValueError):
    pass
process = subprocess.Popen(
    [
        sys.executable,
        str(root / 'manage.py'),
        'runserver',
        f'127.0.0.1:{args.port}',
        '--noreload',
    ],
    cwd=root,
)
try:
    for _ in range(100):
        if process.poll() is not None:
            raise SystemExit('Django server stopped during startup.')
        if ready():
            break
        time.sleep(0.2)
    else:
        raise SystemExit('Local Django server did not become ready.')
    print(
        '\nCaspian Transit Django: ' + entry + '\nKeep this console open. Ctrl+C stops this new local app only.\n',
        flush=True,
    )
    if not args.no_open:
        webbrowser.open(entry)
    process.wait()
except KeyboardInterrupt:
    pass
finally:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
