from zipfile import ZipFile, ZIP_STORED
from xml.etree import ElementTree as ET
import pytest
from app.epub_writer import EpubWriter


def test_manifest_spine_navigation_and_resource_links(tmp_path):
    book=EpubWriter('书名 <测试> & 示例')
    book.add_asset('styles/book.css','text/css',b'body{line-height:1.8}')
    book.add_chapter('one.xhtml','第一章 & 引言','<p>正文 &amp; 文本</p>')
    book.add_chapter('two.xhtml','第二章','<table><tr><td>姓名</td></tr></table>')
    path=tmp_path/'book.epub';book.write(path)
    with ZipFile(path) as archive:
        assert archive.infolist()[0].filename=='mimetype'
        assert archive.infolist()[0].compress_type==ZIP_STORED
        opf=ET.fromstring(archive.read('EPUB/content.opf'))
        ns={'o':'http://www.idpf.org/2007/opf','h':'http://www.w3.org/1999/xhtml'}
        items={x.attrib['id']:x for x in opf.findall('o:manifest/o:item',ns)}
        for item in items.values():
            assert 'EPUB/'+item.attrib['href'] in archive.namelist()
        refs=opf.findall('o:spine/o:itemref',ns)
        assert [items[x.attrib['idref']].attrib['href'] for x in refs]==['one.xhtml','two.xhtml']
        assert sum(item.attrib.get('properties')=='nav' for item in items.values())==1
        nav=ET.fromstring(archive.read('EPUB/nav.xhtml'))
        assert [a.attrib['href'] for a in nav.findall('.//h:a',ns)]==['one.xhtml','two.xhtml']
        for name in archive.namelist():
            if name.endswith(('.xml','.opf','.xhtml','.ncx')): ET.fromstring(archive.read(name))


def test_rejects_unsafe_paths_and_invalid_xhtml():
    book=EpubWriter('Test')
    with pytest.raises(ValueError): book.add_asset('../outside','text/plain',b'x')
    with pytest.raises(ET.ParseError): book.add_chapter('bad.xhtml','Test','<p>broken & text</p>')
