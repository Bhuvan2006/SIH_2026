import json
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@lru_cache
def all_diet_guidance() -> dict:
    raw = json.loads((DATA_DIR / "diet_guidance.json").read_text(encoding="utf-8"))
    raw.pop("_note", None)
    return raw
