from pathlib import Path
from zipfile import ZipFile, ZIP_STORED
import copy
import xml.etree.ElementTree as ET
import pytest
import pypdfium2 as pdfium
from PIL import Image
from app.layout import reconstruct
from app.export import export_book


def row(text, y, score=.99, x=20):
    return [[[x,y],[x+180,y],[x+180,y+20],[x,y+20]], text, score]


def test_chinese_merge_and_confidence():
    blocks = reconstruct([row('这是一段', 20), row('完整的文字。', 45, .7), row('下一段。', 90)], 600, 800)
    assert [b['text'] for b in blocks] == ['这是一段完整的文字。', '下一段。']
    assert blocks[0]['confidence'] == .7
    assert len(blocks[0]['lines']) == 2


def test_english_spacing_and_headings():
    blocks = reconstruct([row('第一章 方法', 0), row('Hello', 40), row('world.', 65)], 600, 800)
    assert blocks[0]['kind'] == 'heading'
    assert blocks[1]['text'] == 'Hello world.'


def test_empty():
    assert reconstruct(None, 100, 100) == []


@pytest.fixture
def book(tmp_path):
    Image.new('RGB', (600, 800), 'white').save(tmp_path / 'page-1.jpg')
    return dict(title='中文测试书', pages=[dict(number=1, retain_original=False, blocks=[
        dict(kind='heading', text='第一章 阅读'), dict(kind='paragraph', text='扫描文字重新排版。A < B & C。' * 80),
        dict(kind='omit', text='IGNORE_ME')])])


def test_pdf_unicode_and_pagination(book, tmp_path):
    path = export_book(book, tmp_path, 'pdf')
    with pdfium.PdfDocument(str(path)) as doc:
        texts = []
        for page in doc:
            textpage = page.get_textpage()
            texts.append(textpage.get_text_range())
            textpage.close()
            page.close()
        text = ''.join(texts)
        assert len(doc) >= 2
        assert '中文测试书' in text and '扫描文字重新排版' in text
        assert 'IGNORE_ME' not in text


def test_epub_valid_xml_and_resources(book, tmp_path):
    path = export_book(book, tmp_path, 'epub', include_originals=True)
    with ZipFile(path) as archive:
        assert archive.infolist()[0].filename == 'mimetype'
        assert archive.infolist()[0].compress_type == ZIP_STORED
        assert archive.read('mimetype') == b'application/epub+zip'
        for name in archive.namelist():
            if name.endswith(('.xhtml', '.opf', '.ncx', '.xml')):
                ET.fromstring(archive.read(name))
        content = archive.read('EPUB/page-1.xhtml').decode()
        assert 'A &lt; B &amp; C' in content
        assert 'IGNORE_ME' not in content
        assert 'EPUB/images/page-1.jpg' in archive.namelist()
        assert 'EPUB/fonts/wenkai.ttf' in archive.namelist()


def test_api_validation_and_edit(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    monkeypatch.setattr(main, 'DATA', tmp_path)
    monkeypatch.setattr(main, 'jobs', {})
    client = TestClient(main.app)
    assert client.post('/api/jobs', files={'file': ('bad.pdf', b'not a pdf')}).status_code == 400
    assert client.get('/api/jobs/missing').status_code == 404
    job = dict(id='test', title='Title', status='ready', pages=[dict(number=1, blocks=[dict(kind='paragraph',text='old',confidence=.9)])])
    main.jobs['test'] = job
    (tmp_path/'test').mkdir()
    changed = dict(title='Revised',pages=[dict(number=1,blocks=[dict(kind='heading',text='new')])])
    assert client.put('/api/jobs/test', json=changed).status_code == 200
    assert job['pages'][0]['blocks'][0]['confidence'] == .9
    assert job['pages'][0]['blocks'][0]['text'] == 'new'
    stale = {**changed, 'revision': 0}
    assert client.put('/api/jobs/test', json=stale).status_code == 409
    assert job['revision'] == 1
    changed['pages'][0]['number'] = 2
    assert client.put('/api/jobs/test',json=changed).status_code == 400
    assert client.post('/api/jobs/test/export',json={'format':'exe'}).status_code == 422
    assert client.get('/api/jobs/test/downloads/source.pdf').status_code == 404


def test_first_line_indent_does_not_split_paragraph():
    blocks = reconstruct([row('首行缩进而且尚未', 20, x=60), row('结束。', 45), row('新的一段', 70, x=60)], 600, 800)
    assert [b['text'] for b in blocks] == ['首行缩进而且尚未结束。', '新的一段']


def test_full_width_tall_line_is_not_heading():
    rows = [row('普通正文', y) for y in (20, 45, 70)]
    rows.append(([[20,100],[580,100],[580,130],[20,130]], '这是一行检测框偏高的普通正文', .9))
    assert all(b['kind'] == 'paragraph' for b in reconstruct(rows,600,800))
