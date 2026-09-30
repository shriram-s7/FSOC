"""Read-only access to new manifests and historical flat session exports."""
import csv
import json
from pathlib import Path
from evaluation.requirements import evaluate

def safe_session(root, sid):
    if not sid or Path(sid).name != sid or any(c in sid for c in '/\\:'):
        raise ValueError('Invalid session ID')
    return Path(root)/sid

def read_session(root, sid):
    folder = safe_session(root, sid)
    manifest = folder/'session.json'
    if manifest.exists():
        return json.loads(manifest.read_text(encoding='utf-8'))
    summary_path = Path(root)/(sid+'_summary.csv')
    if not summary_path.exists():
        raise FileNotFoundError(sid)
    summary = {}
    with summary_path.open(newline='', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            key, value = row['metric'], row['value']
            if value == '': value = None
            elif value in ('PASS', 'FAIL'): value = value == 'PASS'
            elif value in ('true','false'): value = value == 'true'
            else:
                try: value = float(value)
                except ValueError: pass
            summary[key] = value
    summary['session_id'] = sid
    artifacts = {kind: sid+suffix for kind, suffix in [('pdf','_report.pdf'),('summary','_summary.csv'),('frames','_frames.csv')]
                 if (Path(root)/(sid+suffix)).exists()}
    return dict(schema_version=0, session_id=sid, source=summary.get('mode'), status='legacy',
                summary=summary, requirements=evaluate(summary), configuration={}, events=[], artifacts=artifacts,
                completed_at=None, modified=summary_path.stat().st_mtime)

def list_sessions(root):
    ids = {p.name[:-12] for p in Path(root).glob('*_summary.csv')}
    ids.update(p.parent.name for p in Path(root).glob('*/session.json'))
    rows=[]
    for sid in ids:
        try:
            r=read_session(root,sid)
            r['modified'] = max((Path(root)/r['artifacts']['summary']).stat().st_mtime if r.get('artifacts',{}).get('summary') else 0,
                                (Path(root)/sid/'session.json').stat().st_mtime if (Path(root)/sid/'session.json').exists() else 0)
            rows.append(r)
        except (OSError, ValueError, KeyError): continue
    return sorted(rows,key=lambda r:r['modified'],reverse=True)

def session_frames(root, sid, limit=1000):
    record=read_session(root,sid)
    filename=record.get('artifacts',{}).get('frames')
    if not filename: return []
    path=Path(root)/filename
    with path.open(newline='',encoding='utf-8-sig') as f:
        rows=list(csv.DictReader(f))
    step=max(1,(len(rows)+limit-1)//limit)
    sampled=[]
    for i in range(0,len(rows),step):
        bucket=rows[i:i+step]
        point=dict(bucket[-1])
        point['plot_gap']=any(r.get('state')!='LOCKED' for r in bucket)
        sampled.append(point)
    return sampled
