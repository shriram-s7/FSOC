"""End-to-end smoke test against a running FSOC-PAT backend (dev or frozen).

  python packaging/smoke_test.py [base_url]

Covers: static UI, diagnostics, live mission + websocket frames, stop and
session finalisation (CSV + PDF), video preflight + analysis, and a CV/AI/Hybrid
comparison (which spawns worker processes) with its PDF report.
"""
import asyncio
import json
import sys
import time
import urllib.request
import uuid

import websockets

BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8765'
VIDEO = 'input_videos/test_clean.mp4'


def call(path, data=None, raw=None, ctype=None, method=None):
    body = raw if raw is not None else (json.dumps(data).encode() if data is not None else None)
    req = urllib.request.Request(BASE + path, data=body, method=method or ('POST' if body is not None else 'GET'))
    if body is not None:
        req.add_header('Content-Type', ctype or 'application/json')
    with urllib.request.urlopen(req, timeout=180) as r:
        payload = r.read()
        return json.loads(payload) if 'json' in r.headers.get('Content-Type', '') else payload


def multipart(field, filename, content):
    boundary = uuid.uuid4().hex
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
            f'Content-Type: application/octet-stream\r\n\r\n').encode() + content + f'\r\n--{boundary}--\r\n'.encode()
    return body, f'multipart/form-data; boundary={boundary}'


def wait(predicate, timeout, label):
    end = time.time() + timeout
    while time.time() < end:
        value = predicate()
        if value:
            return value
        time.sleep(1)
    raise TimeoutError(label)


def check(label, ok, detail=''):
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    if not ok:
        raise SystemExit(1)


async def frames(n):
    async with websockets.connect(BASE.replace('http', 'ws') + '/ws/frame', max_size=None) as ws:
        got = 0
        while got < n:
            if json.loads(await asyncio.wait_for(ws.recv(), 15)).get('frame'):
                got += 1
    return got


def finish_mission(label):
    call('/api/command', {'cmd': 'stop'})
    fin = wait(lambda: (s := call('/api/finalisation')) and s.get('finalisation') in ('ready', 'error') and s, 120, 'finalisation')
    check(f'{label} finalised', fin.get('finalisation') == 'ready', str(fin)[:200])
    sid = fin['finished_session_id']
    rec = call(f'/api/sessions/{sid}')
    pdf = call(f'/api/sessions/{sid}/artifacts/pdf')
    check(f'{label} PDF report', isinstance(pdf, bytes) and pdf[:4] == b'%PDF', f'{len(pdf)} bytes, session {sid}')
    return rec


def main():
    check('UI index', b'<html' in call('/').lower())
    diag = call('/api/diagnostics')
    check('model loaded', diag['model']['loaded'], diag['system']['torch'])

    call('/api/mission/configure', {})
    call('/api/command', {'cmd': 'run'})
    check('live frames over websocket', asyncio.run(frames(20)) == 20)
    time.sleep(3)
    state = call('/api/state')
    check('simulation advancing', state.get('sim_time', 0) > 0, f"t={state.get('sim_time'):.1f}s fps={state.get('fps'):.1f}")
    finish_mission('simulation mission')

    body, ctype = multipart('file', 'test_clean.mp4', open(VIDEO, 'rb').read())
    meta = call('/api/videos/prepare', raw=body, ctype=ctype)
    check('video preflight', meta.get('frames', 0) > 0, f"{meta.get('frames')} frames")
    call(f"/api/videos/{meta['id']}/start", {'mode': 'Hybrid'})
    call('/api/command', {'cmd': 'run'})
    wait(lambda: call('/api/state').get('sim_time', 0) > 1, 60, 'video playback')
    check('video analysis running', True)
    finish_mission('video mission')

    job = call('/api/comparisons', {'motion': 'straight', 'duration': 3, 'fresh': True})
    m = wait(lambda: (x := call(f"/api/comparisons/{job['id']}")) and x['status'] not in ('queued', 'running') and x, 900, 'comparison')
    check('comparison CV/AI/Hybrid workers', m['status'] == 'complete', str(m.get('error') or m['completed_modes']))
    report = call(f"/api/comparisons/{job['id']}/report")
    check('comparison PDF report', isinstance(report, bytes) and report[:4] == b'%PDF', f'{len(report)} bytes')
    print('ALL CHECKS PASSED')


if __name__ == '__main__':
    main()
