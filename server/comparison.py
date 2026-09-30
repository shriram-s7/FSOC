"""Sequential child processes with persistent comparison manifests."""
import asyncio
import json
import os
import subprocess
import sys
import uuid
import hashlib
from pathlib import Path
from datetime import datetime,timezone
from fastapi import APIRouter,HTTPException
from fastapi.responses import FileResponse
from comparison.scenario import make_scenario

def router_for(root,shared):
    root=Path(root)/'comparisons';root.mkdir(parents=True,exist_ok=True)
    router=APIRouter(prefix='/api/comparisons');tasks={}
    def folder(ident):
        if len(ident)!=32 or any(c not in '0123456789abcdef' for c in ident):raise HTTPException(404)
        p=root/ident
        if not (p/'manifest.json').exists():raise HTTPException(404)
        return p
    def save(p,m):
        tmp=p/'manifest.tmp';tmp.write_text(json.dumps(m,indent=2),encoding='utf-8');os.replace(tmp,p/'manifest.json')
    for manifest in root.glob('*/manifest.json'):
        try:
            previous=json.loads(manifest.read_text())
            if previous.get('status') in ('queued','running'):
                previous.update(status='error',error='Backend restarted before generation completed; generate a new comparison.')
                save(manifest.parent,previous)
        except (OSError,ValueError):pass
    async def generate(p,m):
        try:
            for mode in ('cv','ai','hybrid'):
                if (p/'cancel').exists():raise InterruptedError('Cancelled')
                m.update(status='running',current_mode=mode);save(p,m)
                env=dict(os.environ,FSOC_LOGS_DIR=str(p/'worker-sessions'),PYTHONDONTWRITEBYTECODE='1')
                with (p/(mode+'.log')).open('w') as log:
                    # A frozen build has no interpreter; its launcher dispatches the worker instead.
                    command=[sys.executable,'--comparison-worker'] if getattr(sys,'frozen',False) else [sys.executable,'-B','-m','comparison.worker']
                    process=subprocess.Popen(command+[str(p),mode],
                        cwd=str(Path(__file__).resolve().parents[1]),env=env,stdout=log,stderr=log,
                        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    try:
                        while process.poll() is None:
                            if (p/'cancel').exists() or shared.get('running'):
                                process.terminate();await asyncio.to_thread(process.wait,timeout=10)
                                raise InterruptedError('Cancelled because a live mission started' if shared.get('running') else 'Cancelled')
                            await asyncio.sleep(.25)
                        if process.returncode:raise RuntimeError(f'{mode} worker failed; see {mode}.log')
                    finally:
                        if process.poll() is None:process.terminate()
                result=json.loads((p/mode/'result.json').read_text())
                if result['schedule_hash']!=m['schedule_hash']:raise RuntimeError('Scenario hash mismatch')
                m['completed_modes'].append(mode);save(p,m)
            m.update(status='complete',current_mode=None)
        except InterruptedError as e:m.update(status='cancelled',error=str(e))
        except Exception as e:m.update(status='error',error=str(e))
        finally:save(p,m);shared['comparison_busy']=False
    @router.post('')
    async def create(data:dict):
        if shared.get('running') or shared.get('comparison_busy'):raise HTTPException(409,'Finish or pause the active mission/comparison first')
        try:scenario=make_scenario(data.get('motion','straight'),float(data.get('duration',5)),42,bool(data.get('dropout',False)),data.get('renderer','classic'))
        except (ValueError,TypeError) as e:raise HTTPException(422,str(e))
        project=Path(__file__).resolve().parents[1];fingerprint=hashlib.sha256()
        for group in ('comparison','simulation','tracking','detection','control','disturbance','evaluation','ui'):
            for source in sorted((project/group).glob('*.py')):fingerprint.update(source.read_bytes())
        fingerprint.update((project/'models/beacon_classifier_v2.pt').read_bytes())
        engine_hash=fingerprint.hexdigest()
        if not data.get('fresh',False):
            for previous in root.glob('*/manifest.json'):
                saved=json.loads(previous.read_text())
                if saved.get('status')=='complete' and saved.get('schedule_hash')==scenario['schedule_hash'] and saved.get('engine_hash')==engine_hash:
                    return dict(saved,reused=True)
        if sum(p.stat().st_size for p in root.rglob('*') if p.is_file())>768*1024*1024:
            raise HTTPException(413,'Comparison storage budget reached. Archive unneeded recordings before generating more.')
        ident=uuid.uuid4().hex;p=root/ident;p.mkdir()
        (p/'scenario.json').write_text(json.dumps(scenario),encoding='utf-8')
        m=dict(id=ident,status='queued',motion=scenario['motion'],duration=scenario['duration'],created_at=datetime.now(timezone.utc).isoformat(),
               schedule_hash=scenario['schedule_hash'],engine_hash=engine_hash,completed_modes=[],method='Isolated sequential execution; synchronized recorded playback')
        save(p,m);shared['comparison_busy']=True;tasks[ident]=asyncio.create_task(generate(p,m))
        tasks[ident].add_done_callback(lambda done:tasks.pop(ident,None))
        return m
    @router.get('')
    async def listing():
        return sorted([json.loads(p.read_text()) for p in root.glob('*/manifest.json')],key=lambda m:m['created_at'],reverse=True)
    @router.get('/{ident}')
    async def status(ident:str):
        p=folder(ident);m=json.loads((p/'manifest.json').read_text())
        mode=m.get('current_mode')
        if mode and (p/mode/'progress.json').exists():m['progress']=json.loads((p/mode/'progress.json').read_text())
        total=round(m['duration']*60)
        done=len(m['completed_modes'])*total
        if mode not in m['completed_modes']:done+=m.get('progress',{}).get('frame',0)
        m.update(total_frames=total*3,completed_frames=done,percent=round(100*done/(total*3),1))
        return m
    @router.post('/{ident}/cancel')
    async def cancel(ident:str):
        p=folder(ident);(p/'cancel').touch();return {'status':'cancellation_requested'}
    @router.get('/{ident}/results')
    async def results(ident:str):
        p=folder(ident);m=json.loads((p/'manifest.json').read_text())
        modes={}
        for mode in m['completed_modes']:
            r=json.loads((p/mode/'result.json').read_text());r['telemetry']=[json.loads(l) for l in (p/mode/'telemetry.jsonl').read_text().splitlines()];modes[mode]=r
        from evaluation.comparison_presentation import presentation
        return dict(manifest=m,modes=modes,presentation=presentation(modes))
    @router.get('/{ident}/frames/{mode}/{name}')
    async def frame(ident:str,mode:str,name:str):
        p=folder(ident)
        if mode not in ('cv','ai','hybrid') or len(name)!=9 or not name[:5].isdigit() or name[5:]!='.jpg':raise HTTPException(404)
        path=p/mode/'frames'/name
        if not path.exists():raise HTTPException(404)
        return FileResponse(path)
    @router.get('/{ident}/report')
    async def report(ident:str):
        p=folder(ident)
        if json.loads((p/'manifest.json').read_text())['status']!='complete':raise HTTPException(409,'Comparison is not complete')
        from evaluation.comparison_report import generate
        path=await asyncio.to_thread(generate,p)
        return FileResponse(path,filename='comparison_report.pdf')
    return router
