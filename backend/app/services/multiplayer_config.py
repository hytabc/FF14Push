import json
from app.services.game_config import REPO_ROOT

MULTIPLAYER = json.loads((REPO_ROOT / 'shared/data/multiplayer.json').read_text())
DUNGEONS = {d['id']: d for d in MULTIPLAYER['dungeons']}
