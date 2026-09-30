"""Config loader — reads default.yaml, exposes cfg dict with
attribute-style access at any depth."""
import yaml, os
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / 'default.yaml'

class _A(dict):
    def __getattr__(self, k):
        try:
            v = self[k]
            return _A(v) if isinstance(v, dict) else v
        except KeyError:
            raise AttributeError(k)
    def __setattr__(self, k, v):
        self[k] = v

def load_config(path=CONFIG_PATH):
    with open(path) as f:
        return _A(yaml.safe_load(f))

cfg = load_config()
