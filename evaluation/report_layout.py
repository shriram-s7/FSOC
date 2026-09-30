"""Shared readable session PDF layout; values come from the saved contract."""
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
from reportlab.graphics.shapes import Drawing, Line, String
from evaluation.session_record import make_record
from evaluation.pdf_theme import table_style, footer

NAVY=colors.HexColor('#0a1829')
TEAL=colors.HexColor('#007e96')

def build_pdf(path, record, frames):
    styles=getSampleStyleSheet()
    styles.add(ParagraphStyle('Cell',fontSize=8,leading=11,spaceAfter=0))
    styles.add(ParagraphStyle('SmallNote',fontSize=8,leading=11,textColor=colors.HexColor('#526579')))
    def p(value,style='Cell'):
        return Paragraph(escape(str(value)).replace('\n','<br/>'),styles[style])
    def fmt(value,unit=''):
        if value is None: return 'Not measured'
        if isinstance(value,float): return f'{value:.3f}'.rstrip('0').rstrip('.') + (' '+unit if unit else '')
        return str(value)+(' '+unit if unit else '')
    def table(rows,widths):
        t=Table([[p(c) for c in row] for row in rows],colWidths=widths,repeatRows=1,hAlign='LEFT')
        t.setStyle(table_style())
        return t
    req=record['requirements']; s=record['summary']
    story=[p('FSOC-PAT | Mission performance','Title'),p(record['session_id'],'SmallNote'),Spacer(1,12),
           p(req['overall'].replace('_',' '),'Heading1'),p(req['provenance'],'SmallNote'),p(req['policy'],'SmallNote'),Spacer(1,12)]
    rows=[['Configured requirement','Limit','Measured','Result / explanation']]
    for r in req['rows']:
        rows.append([r['label'],f"{r['operator']} {r['limit']:g} {r['unit']}",fmt(r['value'],r['unit']),r['status'].replace('_',' ')+(f"\n{r['reason']}" if r['reason'] else '')])
    story += [table(rows,[160,75,85,220]),Spacer(1,16),p('Session measurements','Heading2')]
    fields=[('Source','mode',''),('Detector mode','detector_mode',''),('Frames','total_frames',''),
      ('Wall duration','duration_sec','s'),('Source duration','simulation_duration_sec','s'),
      ('Mean end-to-end rate','mean_fps','FPS'),('Pipeline-only rate','processing_fps','FPS'),
      ('Pointing / video centroid RMSE','rmse_px','px'),('Maximum error','max_track_error_px','px'),
      ('Centroid RMSE vs ground truth','centroid_rmse_px','px'),('Correct lock / all frames','correct_lock_pct','%'),
      ('Correct lock / visible frames','correct_lock_visible_pct','%'),('Tracker-state lock','lock_rate_pct','%'),
      ('Beacon outside field of view','beacon_out_of_fov_pct','%'),('Wrong-lock events','wrong_lock_events','')]
    story += [table([['Measurement','Value']]+[[label,fmt(s.get(key),unit)] for label,key,unit in fields],[310,230]),Spacer(1,14)]
    # A bounded plot with explicit gaps; source time is used throughout.
    if frames:
        pts=[]
        for row in frames:
            t=row.get('sim_time')
            if t is None: t=row.get('timestamp_s')
            value=row.get('track_error_px')
            if s.get('mode')=='video':
                coords=[row.get(k) for k in ('tracker_x','tracker_y','gt_x','gt_y')]
                value=((coords[0]-coords[2])**2+(coords[1]-coords[3])**2)**.5 if all(v is not None for v in coords) else None
            if not s.get('scored_with_gt'): value=row.get('confidence')
            if row.get('state')!='LOCKED' and s.get('scored_with_gt'): value=None
            if t is not None: pts.append((float(t),value))
        if pts:
            drawing=Drawing(540,160)
            values=[v for _,v in pts if v is not None]
            ymax=max([1.0]+values)*1.1
            t0,t1=pts[0][0],pts[-1][0]
            drawing.add(Line(35,25,530,25,strokeColor=NAVY)); drawing.add(Line(35,25,35,145,strokeColor=NAVY))
            drawing.add(String(35,8,f'{t0:.2f} s',fontSize=8));drawing.add(String(480,8,f'{t1:.2f} s',fontSize=8))
            drawing.add(String(0,140,f'{ymax:.1f}',fontSize=8))
            previous=None
            stride=max(1,len(pts)//700)
            for i in range(0,len(pts),stride):
                block=pts[i:i+stride]
                t,v=block[-1]
                if v is None or any(b[1] is None for b in block): previous=None; continue
                point=(35+(t-t0)/max(t1-t0,.001)*495,25+float(v)/ymax*120)
                if previous: drawing.add(Line(*previous,*point,strokeColor=TEAL,strokeWidth=.8))
                previous=point
            title='Error (px), source time; gaps indicate no valid locked measurement' if s.get('scored_with_gt') else 'Tracker confidence, source time (not accuracy)'
            story += [KeepTogether([p(title,'Heading2'),drawing]),Spacer(1,12)]
    config=record.get('configuration',{})
    if config:
        rows=[['Configuration','Recorded setting']]
        groups=('camera','detection','source_video') if s.get('mode')=='video' else ('rendering','motion','target','camera','detection','runtime_disturbances')
        for group in groups:
            values=config.get(group,{})
            if values: rows.append([group,'; '.join(f'{key}: {value}' for key,value in values.items() if not isinstance(value,dict))])
        story += [p('Configuration snapshot','Heading2'),table(rows,[220,320])]
    if record.get('events'):
        story += [Spacer(1,12),p('Recorded changes','Heading2'),table([['Source time','Event']]+[[fmt(e.get('time_s'),'s'),str(e)] for e in record['events']],[90,450])]
    SimpleDocTemplate(str(path),pagesize=(612,792),leftMargin=36,rightMargin=36,topMargin=32,bottomMargin=38).build(story,onFirstPage=footer,onLaterPages=footer)
    return str(path)

def generate_session_pdf(metrics, root):
    path=Path(root)/(metrics.session_id+'_report.pdf')
    build_pdf(path,make_record(metrics),metrics.get_frame_data())
    metrics.report_path=str(path)
    return str(path)
