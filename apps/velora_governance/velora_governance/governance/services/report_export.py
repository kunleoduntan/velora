"""Native PDF and DOCX export utilities for sustainability reports.

Optional dependencies are detected at call time. The utilities are framework-neutral
and accept assembled report HTML plus export configuration.
"""
from __future__ import annotations
import re
from html import unescape
from html.parser import HTMLParser
from io import BytesIO
from typing import Any, Mapping


class _ContentParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.blocks=[]; self.current=[]; self.tag_stack=[]; self.table=None; self.row=None; self.cell=None; self.list_stack=[]
    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag in ('h1','h2','h3','h4','p','li'):
            self.flush(); self.current=[]; self.tag_stack.append(tag)
        elif tag=='br': self.current.append('\n')
        elif tag in ('strong','b'): self.current.append('<b>')
        elif tag in ('em','i'): self.current.append('<i>')
        elif tag=='ul': self.list_stack.append('bullet')
        elif tag=='ol': self.list_stack.append('number')
        elif tag=='table': self.flush(); self.table=[]
        elif tag=='tr' and self.table is not None: self.row=[]
        elif tag in ('td','th') and self.row is not None: self.cell=[]
    def handle_endtag(self, tag):
        if tag in ('strong','b'): self.current.append('</b>')
        elif tag in ('em','i'): self.current.append('</i>')
        elif tag in ('h1','h2','h3','h4','p','li'):
            text=''.join(self.current).strip(); self.current=[]
            if text:
                kind=tag
                if tag=='li': kind='li'
                self.blocks.append((kind,text))
            if self.tag_stack: self.tag_stack.pop()
        elif tag in ('td','th') and self.cell is not None:
            self.row.append(''.join(self.cell).strip()); self.cell=None
        elif tag=='tr' and self.row is not None:
            self.table.append(self.row); self.row=None
        elif tag=='table' and self.table is not None:
            if self.table: self.blocks.append(('table',self.table))
            self.table=None
        elif tag in ('ul','ol') and self.list_stack: self.list_stack.pop()
        elif tag in ('article','section','div','nav','header','footer'): self.flush()
    def handle_data(self, data):
        if self.cell is not None: self.cell.append(data)
        else: self.current.append(data)
    def flush(self):
        text=''.join(self.current).strip()
        if text: self.blocks.append(('p',text))
        self.current=[]

def html_blocks(html: str):
    parser=_ContentParser(); parser.feed(html or ''); parser.flush(); return parser.blocks

def _clean_text(value):
    return re.sub(r'\s+',' ',unescape(re.sub(r'<[^>]+>','',str(value)))).strip()

def render_pdf(html: str, config: Mapping[str,Any] | None=None) -> bytes:
    config=dict(config or {})
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, LETTER, landscape
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
    except ImportError as exc: raise RuntimeError('PDF export requires ReportLab') from exc
    buf=BytesIO(); page_size=LETTER if config.get('page_size')=='Letter' else A4
    if config.get('orientation')=='Landscape': page_size=landscape(page_size)
    margin=float(config.get('margin_mm',18))*mm
    doc=SimpleDocTemplate(buf,pagesize=page_size,leftMargin=margin,rightMargin=margin,topMargin=margin+8*mm,bottomMargin=margin+8*mm,title=config.get('title') or 'Sustainability Report',author=config.get('author') or 'Velora Governance')
    styles=getSampleStyleSheet(); styles.add(ParagraphStyle(name='VGTitle',parent=styles['Title'],alignment=TA_CENTER,spaceAfter=16)); styles.add(ParagraphStyle(name='VGBody',parent=styles['BodyText'],leading=15,spaceAfter=7)); styles.add(ParagraphStyle(name='VGH2',parent=styles['Heading2'],spaceBefore=12,spaceAfter=8)); styles.add(ParagraphStyle(name='VGH3',parent=styles['Heading3'],spaceBefore=9,spaceAfter=6))
    story=[]
    cover=config.get('cover_page',True)
    if cover:
        story.extend([Spacer(1,50*mm),Paragraph(config.get('title') or 'Sustainability Report',styles['VGTitle'])])
        if config.get('subtitle'): story.append(Paragraph(config['subtitle'],styles['Heading2']))
        if config.get('entity'): story.append(Paragraph(_clean_text(config['entity']),styles['VGBody']))
        if config.get('period'): story.append(Paragraph(_clean_text(config['period']),styles['VGBody']))
        story.append(PageBreak())
    for kind,value in html_blocks(html):
        if kind in ('h1','h2'): story.append(Paragraph(value,styles['VGH2']))
        elif kind in ('h3','h4'): story.append(Paragraph(value,styles['VGH3']))
        elif kind=='li': story.append(Paragraph('• '+value,styles['VGBody']))
        elif kind=='table':
            rows=[[Paragraph(_clean_text(c),styles['VGBody']) for c in row] for row in value]
            if rows:
                t=Table(rows,repeatRows=1 if len(rows)>1 else 0,hAlign='LEFT')
                t.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.35,colors.grey),('BACKGROUND',(0,0),(-1,0),colors.lightgrey),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5)])); story.append(t); story.append(Spacer(1,6))
        else: story.append(Paragraph(value,styles['VGBody']))
    def decorate(canvas, doc):
        canvas.saveState()
        if config.get('header'): canvas.setFont('Helvetica',8); canvas.drawString(doc.leftMargin, page_size[1]-margin/2, config['header'])
        if config.get('footer'): canvas.setFont('Helvetica',8); canvas.drawString(doc.leftMargin, margin/2, config['footer'])
        if config.get('page_numbers',True): canvas.setFont('Helvetica',8); canvas.drawRightString(page_size[0]-doc.rightMargin, margin/2, f"Page {doc.page}")
        canvas.restoreState()
    doc.build(story,onFirstPage=decorate,onLaterPages=decorate); return buf.getvalue()

def render_docx(html: str, config: Mapping[str,Any] | None=None) -> bytes:
    config=dict(config or {})
    try: from docx import Document
    except ImportError as exc: raise RuntimeError('Word export requires python-docx') from exc
    from docx.shared import Inches, Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.section import WD_SECTION
    doc=Document(); section=doc.sections[0]
    section.top_margin=Inches(float(config.get('margin_inches',0.7))); section.bottom_margin=Inches(float(config.get('margin_inches',0.7)))
    section.left_margin=Inches(float(config.get('margin_inches',0.7))); section.right_margin=Inches(float(config.get('margin_inches',0.7)))
    if config.get('header'):
        section.header.paragraphs[0].text=config['header']
    if config.get('footer'):
        section.footer.paragraphs[0].text=config['footer']
    if config.get('page_numbers',True):
        fp=section.footer.paragraphs[0]; fp.alignment=WD_ALIGN_PARAGRAPH.RIGHT
        fp.add_run('Velora Governance | Page ')
        # Word field for dynamic page numbering.
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        run=fp.add_run()
        begin=OxmlElement('w:fldChar'); begin.set(qn('w:fldCharType'),'begin')
        instr=OxmlElement('w:instrText'); instr.set(qn('xml:space'),'preserve'); instr.text=' PAGE '
        separate=OxmlElement('w:fldChar'); separate.set(qn('w:fldCharType'),'separate')
        text=OxmlElement('w:t'); text.text='1'
        end=OxmlElement('w:fldChar'); end.set(qn('w:fldCharType'),'end')
        run._r.extend([begin,instr,separate,text,end])
    if config.get('cover_page',True):
        p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.space_before=Inches(1.5)
        r=p.add_run(config.get('title') or 'Sustainability Report'); r.bold=True; r.font.size=Pt(28)
        for text in (config.get('subtitle'),config.get('entity'),config.get('period')):
            if text: q=doc.add_paragraph(str(text)); q.alignment=WD_ALIGN_PARAGRAPH.CENTER
        doc.add_page_break()
    for kind,value in html_blocks(html):
        if kind in ('h1','h2'): doc.add_heading(_clean_text(value),level=1 if kind=='h1' else 2)
        elif kind in ('h3','h4'): doc.add_heading(_clean_text(value),level=3)
        elif kind=='li': doc.add_paragraph(_clean_text(value),style='List Bullet')
        elif kind=='table':
            if value:
                table=doc.add_table(rows=0,cols=max(1,max(len(r) for r in value))); table.style='Table Grid'
                for row in value:
                    cells=table.add_row().cells
                    for i,c in enumerate(row):
                        if i<len(cells): cells[i].text=_clean_text(c)
        else: doc.add_paragraph(_clean_text(value))
    out=BytesIO(); doc.save(out); return out.getvalue()

def normalize_export_config(template: Mapping[str,Any] | None=None, overrides: Mapping[str,Any] | None=None) -> dict[str,Any]:
    """Normalize export template settings and apply explicit user overrides."""
    raw=dict(template or {}); raw.update(dict(overrides or {}))
    config={
      'title':raw.get('title') or raw.get('template_name') or 'Sustainability Report',
      'subtitle':raw.get('subtitle') or '', 'entity':raw.get('entity') or '', 'period':raw.get('period') or '',
      'cover_page':bool(raw.get('cover_page',True)), 'header':raw.get('header') or raw.get('header_text') or '',
      'footer':raw.get('footer') or raw.get('footer_text') or '', 'page_numbers':bool(raw.get('page_numbers',True)),
      'page_size':raw.get('page_size') or 'A4', 'orientation':raw.get('orientation') or 'Portrait',
      'margin_mm':float(raw.get('margin_mm',18) or 18), 'margin_inches':float(raw.get('margin_inches',0.7) or 0.7),
      'author':raw.get('author') or 'Velora Governance'}
    if config['page_size'] not in ('A4','Letter'): raise ValueError('Unsupported page size')
    if config['orientation'] not in ('Portrait','Landscape'): raise ValueError('Unsupported page orientation')
    if not 5<=config['margin_mm']<=40: raise ValueError('PDF margin must be between 5 and 40 mm')
    if not 0.25<=config['margin_inches']<=1.5: raise ValueError('Word margin must be between 0.25 and 1.5 inches')
    return config

def compare_revisions(old_html: str, new_html: str) -> dict[str,Any]:
    """Lightweight text comparison summary; not a legal redline."""
    old=_clean_text(old_html); new=_clean_text(new_html)
    old_tokens=old.split(); new_tokens=new.split(); old_set=set(old_tokens); new_set=set(new_tokens)
    return {'old_word_count':len(old_tokens),'new_word_count':len(new_tokens),'added_words':len(new_set-old_set),'removed_words':len(old_set-new_set),'changed':old!=new,'comparison_type':'text-token summary','note':'This is a summary comparison, not a tracked-change redline.'}
