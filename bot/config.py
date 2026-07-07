import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
CACHE_DIR = os.path.join(DATA_DIR, "cache")
LOG_DIR = os.path.join(ROOT, "logs")


def load():
    with open(os.path.join(ROOT, "config.json")) as f:
        cfg = json.load(f)
    for d in (DATA_DIR, CACHE_DIR, LOG_DIR):
        os.makedirs(d, exist_ok=True)
    return cfg
