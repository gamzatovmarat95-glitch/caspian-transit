"""Configure a Windy Point Forecast credential through hidden console input."""
import getpass
import json
import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from caspian.runtime import load_private_settings

runtime = root / '.runtime'
private = load_private_settings(runtime)
key = getpass.getpass('Windy Point Forecast API key (hidden): ').strip()
if not 16 <= len(key) <= 256 or any(c.isspace() for c in key):
    raise SystemExit('Invalid key format; nothing changed.')
private['windy_point_api_key'] = key
temporary = runtime / 'private-windy.tmp'
temporary.write_text(json.dumps(private, ensure_ascii=False, indent=2), encoding='utf-8')
os.replace(temporary, runtime / 'private.json')
print('Point Forecast key saved privately. Restart only Django; select Windy in mathematical calculation.')
