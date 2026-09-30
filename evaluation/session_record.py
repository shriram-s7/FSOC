"""Portable versioned session manifests, atomically published after exports."""
import json
import os
from pathlib import Path
from datetime import datetime, timezone
from evaluation.requirements import evaluate

def make_record(metrics, artifacts=None, status='complete'):
    summary = metrics.compute_summary()
    return dict(schema_version=1, session_id=metrics.session_id, source=metrics.mode,
                status=status, created_at=getattr(metrics, 'created_at', datetime.now(timezone.utc).isoformat()),
                completed_at=datetime.now(timezone.utc).isoformat(),
                configuration=getattr(metrics, 'configuration', {}),
                events=getattr(metrics, 'events', []), summary=summary,
                requirements=evaluate(summary), artifacts=artifacts or {},
                model='BeaconCNN v2',scoring_version='3-ps-strict-loss',
                time_basis={'duration_sec': 'wall time', 'simulation_duration_sec': 'source simulation time',
                            'acquisition_time_s': 'GT: first in-FOV to correct lock; no GT: first candidate to lock'})

def save_record(root, record):
    directory = Path(root) / record['session_id']
    directory.mkdir(parents=True, exist_ok=True)
    temporary = directory / 'session.json.tmp'
    temporary.write_text(json.dumps(record, indent=2, allow_nan=False), encoding='utf-8')
    os.replace(temporary, directory/'session.json')
    return directory/'session.json'
