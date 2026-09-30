"""Scenario loading for the test harness (see harness/scenarios.yaml)."""
import copy
from pathlib import Path

import yaml

SCENARIO_FILE = Path(__file__).parent / 'scenarios.yaml'

# Scenario fields that map onto the live app's shared_state['disturbances']
# dict (the same dict the web UI writes and SimulationThread.step() reads).
DISTURBANCE_FIELDS = ('atmosphere', 'noise_level', 'noise_types',
                      'camera_jitter', 'turbulence', 'scintillation', 'jerk',
                      'platform_motion', 'platform_speed_px_s', 'low_light')


def load_scenarios(path=SCENARIO_FILE):
    """Return {name: fully-resolved scenario dict}, in file order."""
    with open(path) as f:
        doc = yaml.safe_load(f)
    defaults = doc.get('defaults', {})
    out = {}
    for name, body in doc['scenarios'].items():
        sc = copy.deepcopy(defaults)
        sc.update(copy.deepcopy(body or {}))
        sc['name'] = name
        out[name] = sc
    return out


def disturbances_dict(sc):
    """Scenario disturbance fields -> shared_state['disturbances'] dict."""
    types = set(sc.get('noise_types') or [])
    return {
        'turbulence':       float(sc.get('turbulence', 0.0)),
        'vibration':        float(sc.get('camera_jitter', 0.0)),
        'noise':            float(sc.get('noise_level', 0.0)),
        'scintillation':    float(sc.get('scintillation', 0.0)),
        'jerk':             float(sc.get('jerk', 0.0)),
        'atmosphere':       str(sc.get('atmosphere', 'clear')),
        'noise_gaussian':   'gaussian' in types,
        'noise_saltpepper': 'saltpepper' in types,
        'noise_poisson':    'poisson' in types,
        'platform_enabled': str(sc.get('platform_motion', 'none')) != 'none',
        'platform_speed':   float(sc.get('platform_speed_px_s', 10.0)),
        'low_light':        bool(sc.get('low_light', False)),
    }
