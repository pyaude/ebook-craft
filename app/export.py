from pathlib import Path
from html import escape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, PageBreak, Table, TableStyle
from reportlab.lib.utils import ImageReader
from .epub_writer import EpubWriter
from .figures import page_content
from .structure import grid_cells

ROOT = Path(__file__).resolve().parent.parent


def export_book(job, directory, fmt, font_size=11, leading=1.8, page_size='A5', include_originals=False):
    font = ROOT / 'assets/LXGWWenKai-Regular.ttf'
    if not font.exists():
        raise ValueError('缺少中文字体，请运行 python scripts/setup_font.py')
    title = job['title']
    output = directory / f'book.{fmt}'
    if fmt == 'pdf':
        if 'WenKai' not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont('WenKai', str(font)))
        from reportlab.lib.pagesizes import A4, A5
        size = A4 if page_size == 'A4' else A5
        body = ParagraphStyle('body', fontName='WenKai', fontSize=font_size, leading=font_size * leading,
                              wordWrap='CJK', firstLineIndent=font_size * 2, spaceAfter=font_size * .65, alignment=TA_JUSTIFY)
        heading = ParagraphStyle('heading', parent=body, fontSize=font_size * 1.5, leading=font_size * 2.1, spaceBefore=18, spaceAfter=12, keepWithNext=True, firstLineIndent=0, alignment=0)
        story = [Paragraph(escape(title), heading), Spacer(1, 20)]
        for page in job['pages']:
            for kind, block in page_content(page):
                if kind == 'text' and block['kind'] == 'grid':
                    cells = grid_cells(block['text'])
                    if cells:
                        cell_style = ParagraphStyle('cell', parent=body, firstLineIndent=0, alignment=1, spaceAfter=0)
                        table = Table([[Paragraph(escape(cell).replace(chr(10), '<br/>'), cell_style) for cell in row] for row in cells], colWidths=[(size[0]-84)/len(cells[0])]*len(cells[0]), hAlign='CENTER')
                        table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'), ('TOPPADDING',(0,0),(-1,-1),6), ('BOTTOMPADDING',(0,0),(-1,-1),6)]))
                        story.extend([Spacer(1,10),table,Spacer(1,12)])
                    continue
                if kind == 'figure':
                    path = directory / block['file']
                    w, h = ImageReader(str(path)).getSize()
                    factor = min((size[0] - 96) / w, (size[1] - 150) / h, 1.)
                    story.extend([Spacer(1, 10), Image(str(path), w * factor, h * factor)])
                    if block.get('caption'):
                        story.append(Paragraph(escape(block['caption']), body))
                    story.append(Spacer(1, 12))
                    continue
                if block['kind'] != 'omit' and block['text'].strip():
                    style = heading if block['kind'] == 'heading' else body
                    if block.get('alignment') == 'center':
                        style = ParagraphStyle('centered', parent=style, alignment=1, firstLineIndent=0)
                    story.append(Paragraph(escape(block['text']).replace('\n', '<br/>'), style))
            if include_originals or page.get('retain_original') or (not page['blocks'] and not any(f.get('included', True) for f in page.get('figures', []))):
                path = directory / f"raw-{page['number']}.jpg"
                if not path.exists():
                    path = directory / f"page-{page['number']}.jpg"
                w, h = ImageReader(str(path)).getSize()
                factor = min((size[0] - 84) / w, (size[1] - 100) / h)
                story.extend([PageBreak(), Image(str(path), w * factor, h * factor), PageBreak()])
        def footer(canvas, doc):
            canvas.setFont('WenKai', 8)
            canvas.setFillColorRGB(.45, .45, .45)
            canvas.drawCentredString(size[0] / 2, 23, str(doc.page))
        SimpleDocTemplate(str(output), pagesize=size, rightMargin=42, leftMargin=42, topMargin=42, bottomMargin=42, title=title, author='').build(story, onFirstPage=footer, onLaterPages=footer)
    else:
        book = EpubWriter(title)
        css = '@font-face{font-family:WenKai;src:url("../fonts/wenkai.ttf")}body{font-family:WenKai,serif;line-height:1.8;margin:5%;}p{text-align:justify;text-indent:2em;}h1{font-size:1.5em;}img{max-width:100%;height:auto}.author-grid{width:100%;table-layout:fixed;border-collapse:collapse;margin:1em 0}.author-grid td{text-align:center;vertical-align:top;padding:.5em;overflow-wrap:anywhere}.centered{text-align:center;text-indent:0}'
        book.add_asset('fonts/wenkai.ttf', 'font/ttf', font.read_bytes())
        book.add_asset('styles/book.css', 'text/css', css.encode())
        license_path = ROOT / 'assets/OFL.txt'
        if license_path.exists():
            book.add_asset('licenses/OFL.txt', 'text/plain', license_path.read_bytes())
        for page in job['pages']:
            chapter_title = f"原书第 {page['number']} 页"
            content = []
            for kind, block in page_content(page):
                if kind == 'text' and block['kind'] == 'grid':
                    cells = grid_cells(block['text'])
                    if cells:
                        content.append('<table class="author-grid"><tbody>' + ''.join('<tr>' + ''.join('<td>' + escape(cell) + '</td>' for cell in row) + '</tr>' for row in cells) + '</tbody></table>')
                    continue
                if kind == 'figure':
                    name = f"images/{block['file']}"
                    book.add_asset(name, 'image/png', (directory / block['file']).read_bytes())
                    caption = escape(block.get('caption', ''))
                    content.append(f'<figure><img src="{name}" alt="{caption or "原页插图"}"/>' + (f'<figcaption>{caption}</figcaption>' if caption else '') + '</figure>')
                    continue
                if block['kind'] == 'omit' or not block['text'].strip():
                    continue
                tag = 'h1' if block['kind'] == 'heading' else 'p'
                if tag == 'h1':
                    chapter_title = block['text'][:80]
                align = ' class="centered"' if block.get('alignment') == 'center' else ''
                content.append(f'<{tag}{align}>{escape(block["text"]).replace(chr(10), "<br/>")}</{tag}>')
            if include_originals or page.get('retain_original') or (not page['blocks'] and not any(f.get('included', True) for f in page.get('figures', []))):
                name = f"images/page-{page['number']}.jpg"
                book.add_asset(name, 'image/jpeg', ((directory / f"raw-{page['number']}.jpg") if (directory / f"raw-{page['number']}.jpg").exists() else (directory / f"page-{page['number']}.jpg")).read_bytes())
                content.append(f'<img src="{name}" alt="原书第 {page["number"]} 页扫描图"/>')
            book.add_chapter(f"page-{page['number']}.xhtml", chapter_title, ''.join(content) or '<p>本页无正文。</p>')
        book.write(output)
    return output
