"""A ReportLab hook for one image-math atom's approved logical string.
Native prose stays native; this is not editable two-dimensional mathematics.
"""
from reportlab.pdfbase import pdfmetrics
def draw_logical_image_text(canvas, text, x, baseline, width, font_for, size):
    if not text or width<=0:return
    segments=[]
    for ch in text:
        font=font_for(ch)
        if segments and segments[-1][0]==font:segments[-1][1]+=ch
        else:segments.append([font,ch])
    natural=sum(pdfmetrics.stringWidth(s,font,size) for font,s in segments)
    if natural<=0:raise ValueError('EMPTY_LOGICAL_WIDTH')
    canvas.saveState()
    try:
        t=canvas.beginText(x,baseline);t.setTextRenderMode(3);t.setHorizScale(width/natural*100)
        for font,s in segments:t.setFont(font,size);t.textOut(s)
        canvas.drawText(t)
    finally:canvas.restoreState()
