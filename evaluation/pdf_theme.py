"""Common typography, table styling and footer for application exports."""
from reportlab.lib import colors
from reportlab.platypus import TableStyle

def table_style():
    return TableStyle([
        ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#dceaf0')),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f2f6f9')]),
        ('VALIGN',(0,0),(-1,-1),'TOP'),
        ('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6),
        ('LINEBELOW',(0,0),(-1,0),.6,colors.HexColor('#007e96'))])

def footer(canvas,doc):
    canvas.setFont('Helvetica',8);canvas.setFillColor(colors.HexColor('#526579'))
    canvas.drawString(36,23,'FSOC-PAT | Measured software evaluation | Not independent certification')
    canvas.drawRightString(576,23,str(doc.page))
