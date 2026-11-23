"""Selectable-text, single-column resume PDF from a validated tailored draft."""
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape
import reportlab
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, KeepTogether
from .tailoring import validate_draft


def render_pdf(draft):
    validate_draft(draft.result,draft.sources['items'])
    font_root=Path(reportlab.__file__).parent/'fonts'
    if 'ResumeSans' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('ResumeSans',str(font_root/'Vera.ttf')))
        pdfmetrics.registerFont(TTFont('ResumeSansBold',str(font_root/'VeraBd.ttf')))
        pdfmetrics.registerFontFamily('ResumeSans',normal='ResumeSans',bold='ResumeSansBold')
    styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name='ResumeName',fontName='ResumeSansBold',fontSize=19,leading=24,spaceAfter=6,textColor=colors.HexColor('#183448')))
    styles.add(ParagraphStyle(name='ResumeContact',fontName='ResumeSans',fontSize=8.3,leading=12,spaceAfter=8,textColor=colors.HexColor('#445566'),wordWrap='CJK'))
    styles.add(ParagraphStyle(name='ResumeSection',fontName='ResumeSansBold',fontSize=10.5,leading=15,spaceBefore=13,spaceAfter=6,keepWithNext=True,textColor=colors.HexColor('#1b5360')))
    styles.add(ParagraphStyle(name='ResumeBody',fontName='ResumeSans',fontSize=9.2,leading=13.5,spaceAfter=5))
    styles.add(ParagraphStyle(name='ResumeMeta',fontName='ResumeSansBold',fontSize=9.3,leading=13.5,spaceAfter=4,keepWithNext=True))
    styles.add(ParagraphStyle(name='ResumeBullet',fontName='ResumeSans',fontSize=9.1,leading=13.5,leftIndent=9,firstLineIndent=-7,spaceAfter=4))
    buffer=BytesIO()
    doc=SimpleDocTemplate(buffer,pagesize=A4,rightMargin=43,leftMargin=43,topMargin=35,bottomMargin=35,
                         title='Resume',author='',subject='Candidate resume')
    content=draft.result['resume'];identity=content.get('identity',{})
    name=identity.get('name',{}).get('text') or 'Resume'
    story=[Paragraph(escape(name),styles['ResumeName'])]
    contacts=[item['text'] for item in identity.get('contact',[]) if item.get('text')]
    if contacts:story.append(Paragraph(escape(' | '.join(contacts)),styles['ResumeContact']))
    story.append(HRFlowable(width='100%',thickness=.8,color=colors.HexColor('#bdd0d7'),spaceAfter=7))
    if content.get('summary',{}).get('text'):
        story += [Paragraph('PROFILE',styles['ResumeSection']),Paragraph(escape(content['summary']['text']),styles['ResumeBody'])]
    if content.get('skills'):
        story += [Paragraph('SKILLS',styles['ResumeSection']),Paragraph(escape(' | '.join(item['name'] for item in content['skills'])),styles['ResumeBody'])]
    for section,label in [('experience','EXPERIENCE'),('projects','PROJECTS'),('education','EDUCATION'),('certifications','CERTIFICATIONS')]:
        if not content.get(section):continue
        story.append(Paragraph(label,styles['ResumeSection']))
        for item in content[section]:
            heading=' | '.join(str(item.get(key,'')) for key in ['title','name','company'] if item.get(key))
            heading=heading or item.get('source_heading','')
            if item.get('dates'):heading+=(' | ' if heading else '')+item['dates']
            bullets=item.get('bullets',[])
            if heading:
                head=Paragraph(escape(heading),styles['ResumeMeta'])
                if bullets:
                    story.append(KeepTogether([head,Paragraph('- '+escape(bullets[0]['text']),styles['ResumeBullet'])]))
                    bullets=bullets[1:]
                else:story.append(head)
            for bullet in bullets:story.append(Paragraph('- '+escape(bullet['text']),styles['ResumeBullet']))
            story.append(Spacer(1,4))
    def footer(canvas,document):
        canvas.saveState();canvas.setFont('ResumeSans',7)
        canvas.setFillColor(colors.HexColor('#71808b'))
        canvas.drawRightString(A4[0]-43,21,str(document.page));canvas.restoreState()
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    return buffer.getvalue()
