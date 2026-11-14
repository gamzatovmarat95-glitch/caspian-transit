"""Load installation-local secrets without putting their values in source code."""
import json
import secrets
import hashlib
from pathlib import Path


def installation_id(base_dir, database):
    """Identify this local checkout without exposing its path or any credential."""
    value = str(Path(base_dir).resolve()) + '\n' + str(Path(database).resolve())
    return hashlib.sha256(value.encode('utf-8')).hexdigest()[:16]


def load_private_settings(directory):
    directory.mkdir(exist_ok=True)
    path = directory / 'private.json'
    if not path.exists():
        try:
            with path.open('x', encoding='utf-8') as stream:
                json.dump(
                    {
                        'django_secret': secrets.token_urlsafe(64),
                        'gateway_secret': secrets.token_urlsafe(48),
                    },
                    stream,
                )
        except FileExistsError:
            pass
    return json.loads(path.read_text(encoding='utf-8'))
