"""Prepared video inspection; no simulation changes until explicit Start."""
import csv
import json
import math
import uuid
from pathlib import Path
import cv2
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse

def router_for(root, start):
    router=APIRouter(prefix='/api/videos')
    root=Path(root)/'prepared'
    root.mkdir(parents=True,exist_ok=True)
    def folder(ident):
        if len(ident)!=32 or any(c not in '0123456789abcdef' for c in ident): raise HTTPException(404,'Unknown prepared video')
        p=root/ident
        if not (p/'metadata.json').is_file(): raise HTTPException(404,'Unknown prepared video')
        return p
    @router.post('/prepare')
    async def prepare(file: UploadFile=File(...)):
        if sum(p.stat().st_size for p in root.rglob('*') if p.is_file()) > 1536*1024*1024:
            raise HTTPException(413,'Prepared video storage is full (2 GB budget). Archive unneeded prepared videos before uploading more.')
        ident=uuid.uuid4().hex;p=root/ident;p.mkdir()
        path=p/'source.mp4'
        total=0
        with path.open('wb') as f:
            while chunk:=await file.read(1024*1024):
                total+=len(chunk)
                if total>512*1024*1024:
                    f.close();path.unlink(missing_ok=True)
                    raise HTTPException(413,'Video exceeds 512 MB limit')
                f.write(chunk)
        cap=cv2.VideoCapture(str(path))
        try:
            ok,frame=cap.read()
            if not ok: raise HTTPException(422,'Cannot decode video')
            h,w=frame.shape[:2];fps=cap.get(cv2.CAP_PROP_FPS);count=int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if not math.isfinite(fps) or fps<=0: raise HTTPException(422,'Video has no valid frame rate')
            fourcc=int(cap.get(cv2.CAP_PROP_FOURCC))
            meta=dict(id=ident,name=Path(file.filename or 'video.mp4').name,width=w,height=h,fps=fps,frames=count,
                      duration=count/fps,bytes=total,codec=''.join(chr((fourcc>>(i*8))&255) for i in range(4)),
                      gt_loaded=False,transform='Resize to 640 × 480 (independent horizontal/vertical scaling)')
            thumbs=[]
            for i in range(8):
                index=int(max(0,count-1)*i/7);cap.set(cv2.CAP_PROP_POS_FRAMES,index);ok,img=cap.read()
                if ok:
                    name=f'thumb-{i}.jpg';cv2.imwrite(str(p/name),cv2.resize(img,(160,100)))
                    thumbs.append(dict(frame=index,url=f'/api/videos/{ident}/{name}'))
            meta['thumbnails']=thumbs
            (p/'metadata.json').write_text(json.dumps(meta),encoding='utf-8')
            return meta
        finally:cap.release()
    @router.post('/{ident}/gt')
    async def attach_gt(ident: str, file: UploadFile=File(...), coordinates: str=Form('processing'), index_base: int=Form(0)):
        p=folder(ident);meta=json.loads((p/'metadata.json').read_text())
        if coordinates not in ('native','processing') or index_base not in (0,1):raise HTTPException(422,'Invalid GT convention')
        content=await file.read(10*1024*1024+1)
        if len(content)>10*1024*1024:raise HTTPException(413,'GT file exceeds 10 MB')
        try:
            reader=csv.DictReader(content.decode('utf-8-sig').splitlines())
            if not {'frame','x','y'}.issubset(reader.fieldnames or []):raise ValueError('Required columns: frame,x,y')
            rows=[];seen=set()
            for row in reader:
                n=int(row['frame'])-index_base
                visible=str(row.get('visible','1')).strip().lower() not in ('0','false','no')
                x,y=(float(row['x']),float(row['y'])) if visible else (0.,0.)
                if n<0 or n>=meta['frames'] or n in seen or not all(map(math.isfinite,(x,y))):raise ValueError('Invalid, duplicate or out-of-range frame/coordinate')
                seen.add(n)
                if coordinates=='native':x*=640/meta['width'];y*=480/meta['height']
                rows.append([n,x,y,int(visible)])
            if not rows:raise ValueError('GT CSV contains no rows')
        except (ValueError,UnicodeError,KeyError) as ex:raise HTTPException(422,str(ex))
        with (p/'ground_truth.csv').open('w',newline='') as f:
            writer=csv.writer(f);writer.writerow(['frame','x','y','visible']);writer.writerows(rows)
        meta.update(gt_loaded=True,gt_coordinates=coordinates,gt_index_base=index_base,gt_rows=len(rows))
        (p/'metadata.json').write_text(json.dumps(meta),encoding='utf-8');return meta
    @router.post('/{ident}/start')
    async def run(ident: str, settings: dict):
        p=folder(ident);meta=json.loads((p/'metadata.json').read_text())
        mode=settings.get('mode','Hybrid')
        if mode not in ('CV Only','AI Only','Hybrid'):raise HTTPException(422,'Invalid detector mode')
        return await start(p,meta,mode)
    @router.get('/{ident}/{name}')
    async def thumbnail(ident: str,name: str):
        p=folder(ident)
        if name not in [f'thumb-{i}.jpg' for i in range(8)] or not (p/name).exists():raise HTTPException(404)
        return FileResponse(p/name)
    return router
