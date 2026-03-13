"""utils/file_loader.py — file reading helpers."""
import json, os
def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path
