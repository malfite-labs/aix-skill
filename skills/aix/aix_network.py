"""Runtime network constants from the release's architecture-derived config."""
import json
import pathlib
import urllib.parse

path = pathlib.Path(__file__).with_name('network_config.json')
if path.is_file():
    config = json.loads(path.read_text(encoding='utf-8'))
else:
    # Source checkout only. Installed releases always contain network_config.
    architecture = pathlib.Path(__file__).resolve().parents[2] / 'AIX_ARCHITECTURE.json'
    config = json.loads(architecture.read_text(encoding='utf-8'))
CANONICAL_BETA = config['beta']
PUBLIC_SKILL = config['skill']
BETA_HOST = urllib.parse.urlsplit(CANONICAL_BETA).hostname
root_host = urllib.parse.urlsplit(config['root']).hostname
if root_host != 'aixprotocol.org' or CANONICAL_BETA != 'https://beta.' + root_host:
    raise ValueError('invalid canonical Beta configuration')
if config.get('credential_host', config.get('credentials', {}).get('allowed_host')) != BETA_HOST:
    raise ValueError('invalid protocol credential host scope')
