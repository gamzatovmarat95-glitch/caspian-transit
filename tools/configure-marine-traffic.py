"""Configure a MarineTraffic service credential through hidden console input."""
from pathlib import Path
import getpass
import json
import os
import re
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from caspian.runtime import load_private_settings

runtime = root / '.runtime'
private = load_private_settings(runtime)
key = getpass.getpass('MarineTraffic custom-area API key (hidden): ').strip()
if not re.fullmatch(r'[0-9a-fA-F]{40}', key):
    raise SystemExit('Expected the documented 40-character hexadecimal service key; nothing changed.')
private['marinetraffic_api_key'] = key
temporary = runtime / 'private-marine.tmp'
with temporary.open('w', encoding='utf-8') as stream:
    json.dump(private, stream, ensure_ascii=False, indent=2)
os.replace(temporary, runtime / 'private.json')
print('Key saved privately. Restart only this Django app. Check service area and contracted call interval.')
