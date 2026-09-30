"""Comparison evidence, without a predetermined winner or certification."""
import json
from xml.sax.saxutils import escape
from reportlab.platypus import SimpleDocTemplate,Paragraph,Table,TableStyle,Spacer,PageBreak,KeepTogether
from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
from reportlab.lib import colors
from reportlab.graphics.shapes import Drawing,Line,String
from evaluation.pdf_theme import table_style, footer
from evaluation.comparison_presentation import presentation, MODES

def generate(root):
    manifest=json.loads((root/'manifest.json').read_text());scenario=json.loads((root/'scenario.json').read_text())
    modes={mode:json.loads((root/mode/'result.json').read_text()) for mode in ('cv','ai','hybrid')}
    styles=getSampleStyleSheet();styles.add(ParagraphStyle('Cell',fontSize=8,leading=11))
    def p(s,style='Cell'):return Paragraph(escape(str(s)),styles[style])
    def fmt(x):return 'Not measured' if x is None else f'{x:.3f}' if isinstance(x,float) else str(x)
    def table(rows,widths):
        t=Table([[p(c) for c in row] for row in rows],colWidths=widths,repeatRows=1)
        t.setStyle(table_style());return t
    story=[p('FSOC-PAT | Tracking comparison - BETA','Title'),p(manifest['id']),Spacer(1,10),p(manifest['method'],'Heading2'),p(f"Motion: {manifest['motion']} | Source duration: {manifest['duration']} s | Seed: {scenario['seed']} | Fixed step: 1/60 s"),p(scenario['description']),p('Each mode has an independent camera and tracker. The target and exogenous disturbance schedule are identical. Images may differ because the cameras point differently. No mode was tuned for this comparison.'),Spacer(1,12)]
    fields=[('Pointing RMSE (px)','rmse_px'),('Mean pointing error (px)','mean_track_error_px'),('Maximum pointing error (px)','max_track_error_px'),('Centroid RMSE vs GT (px)','centroid_rmse_px'),('Correct lock / all frames (%)','correct_lock_pct'),('Correct lock / visible frames (%)','correct_lock_visible_pct'),('Target loss (%)','target_loss_pct'),('Acquisition (s)','acquisition_time_s'),('Reacquisition mean (s)','reacq_time_s'),('Pipeline-only rate (FPS)','processing_fps'),('Unpaced compute throughput (FPS)','unpaced_compute_fps'),('Valid live error samples','valid_error_frames')]
    story.append(table([['Measured quantity','CV','AI','Hybrid']]+[[label]+[fmt(modes[m]['summary'].get(key)) for m in modes] for label,key in fields],[240,100,100,100]))
    display=presentation(modes)
    story += [Spacer(1,12),p('Three approaches | Hybrid featured','Heading2'),p(display['note'])]
    story.append(table([['Metric','Better direction','Measured leader(s)']]+[
        [r['label'],r['direction'],(', '.join(m.upper() for m in r['leaders']) or 'Not measured')+(' (available modes only)' if not r['complete'] else '')]
        for r in display['metrics']],[240,100,200]))
    story += [Spacer(1,12),p('Unpaced generation and playback are not a paced realtime performance test. The end-to-end PS throughput check is NOT TESTED in this report.'),PageBreak(),p('Tracking error over source time','Heading1')]
    streams={m:[json.loads(l) for l in (root/m/'telemetry.jsonl').read_text().splitlines()] for m in modes}
    ymax=max([1.]+[t['track_error_px'] for ts in streams.values() for t in ts if t.get('track_error_px') is not None])*1.1
    d=Drawing(540,250);d.add(Line(35,30,530,30));d.add(Line(35,30,35,230));d.add(String(35,10,'Source time (s)',fontSize=9));d.add(String(0,242,'Error (px)',fontSize=8))
    for tick in range(5):
        y=30+tick/4*190;d.add(String(0,y,f'{ymax*tick/4:.1f}',fontSize=8))
    palette=[m['print_color'] for m in MODES]
    for index,(mode,ts) in enumerate(streams.items()):
        color=colors.HexColor(palette[index]);d.add(String(100+index*140,235,mode.upper(),fontSize=10,fillColor=color));previous=None
        stride=max(1,len(ts)//700)
        for i in range(0,len(ts),stride):
            block=ts[i:i+stride];t=block[-1];v=t.get('track_error_px')
            if v is None or any(r.get('track_error_px') is None for r in block):previous=None;continue
            pt=(35+t['time_s']/manifest['duration']*495,30+v/ymax*190)
            if previous:d.add(Line(*previous,*pt,strokeColor=color,strokeWidth=2.4 if mode=='hybrid' else 1.2,strokeDashArray=[[5,3],[2,3],None][index]))
            previous=pt
    for tick in range(6):
        x=35+tick/5*495;d.add(Line(x,27,x,30));d.add(String(x-5,16,f"{manifest['duration']*tick/5:g}",fontSize=8))
    story += [d,p('Source time is simulated mission time, not the time spent generating this comparison. CV: amber dashed; AI: purple dotted; Hybrid: teal bold solid. Equal traces can overlap. Gaps indicate unavailable locked error; they do not mean zero error. Values are measured, not illustrative.'),Spacer(1,15)]
    for mode,r in modes.items():
        story += [KeepTogether([p(mode.upper()+' | '+r['requirements']['overall'],'Heading2'),table([['Configured check','Limit','Value','Outcome / reason']]+[[x['label'],f"{x['operator']} {x['limit']} {x['unit']}",fmt(x['value']),x['status']+' '+x['reason']] for x in r['requirements']['rows']],[155,85,85,215])]),Spacer(1,12)]
    story += [p('Provenance','Heading2'),p('Schedule SHA-256: '+manifest['schedule_hash']),p('Renderer: '+scenario['configuration'].get('rendering',{}).get('profile','classic')),p('Model: existing BeaconCNN v2 shared by AI scanner and Hybrid classifier; CV uses classical scoring. No retraining. Hybrid is visually featured, not guaranteed to win. Optical rendering, if selected, is a synthetic experiment and has not been validated against real space-camera data.'),p('Requirements are the configured application checks, not independent certification. All mode results, including failures and untested criteria, are retained.')]
    story.append(p('Requirement rows retain the recorded scoring policy. Historical runs may show the previous <= 5% loss boundary; new runs use the supplied statement\'s strict < 5% boundary. Regenerate a run to evaluate under the current policy.'))
    path=root/'comparison_report.pdf'
    SimpleDocTemplate(str(path),pagesize=(612,792),leftMargin=36,rightMargin=36,topMargin=32,bottomMargin=38).build(story,onFirstPage=footer,onLaterPages=footer)
    return path
