"""Minimal EPUB 3 packager written for this project using the Python stdlib."""
from datetime import datetime, timezone
from html import escape
from pathlib import PurePosixPath
from uuid import uuid4
from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED
import xml.etree.ElementTree as ET

XML = '<?xml version="1.0" encoding="utf-8"?>\n'


def xhtml(title, body, language):
    document = (XML + f'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{escape(language)}" xml:lang="{escape(language)}">'
                f'<head><title>{escape(title)}</title><link rel="stylesheet" type="text/css" href="styles/book.css"/></head><body>{body}</body></html>')
    ET.fromstring(document)  # Reject malformed content before creating the archive.
    return document.encode('utf-8')


class EpubWriter:
    def __init__(self, title, language='zh-CN'):
        self.title = title
        self.language = language
        self.identifier = str(uuid4())
        self.assets = {}
        self.chapters = []

    def add_asset(self, name, media_type, content):
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or name in ('content.opf', 'nav.xhtml', 'toc.ncx'):
            raise ValueError('无效的 EPUB 资源路径')
        if name in self.assets:
            raise ValueError('重复的 EPUB 资源路径')
        self.assets[name] = (media_type, content)

    def add_chapter(self, name, title, body):
        self.add_asset(name, 'application/xhtml+xml', xhtml(title, body, self.language))
        self.chapters.append((name, title))

    def write(self, output):
        if not self.chapters:
            raise ValueError('EPUB 至少需要一个章节')
        links = ''.join(f'<li><a href="{escape(name)}">{escape(title)}</a></li>' for name, title in self.chapters)
        nav = xhtml(self.title, f'<nav epub:type="toc" id="toc"><h1>目录</h1><ol>{links}</ol></nav>', self.language)
        points = ''.join(f'<navPoint id="point-{i}" playOrder="{i}"><navLabel><text>{escape(title)}</text></navLabel><content src="{escape(name)}"/></navPoint>' for i,(name,title) in enumerate(self.chapters,1))
        ncx = (XML + f'<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><head><meta name="dtb:uid" content="{self.identifier}"/><meta name="dtb:depth" content="1"/><meta name="dtb:totalPageCount" content="0"/><meta name="dtb:maxPageNumber" content="0"/></head><docTitle><text>{escape(self.title)}</text></docTitle><navMap>{points}</navMap></ncx>').encode()
        assets = {**self.assets, 'nav.xhtml': ('application/xhtml+xml', nav), 'toc.ncx': ('application/x-dtbncx+xml', ncx)}
        ids = {name: f'item-{i}' for i,name in enumerate(assets)}
        manifest = ''.join(f'<item id="{ids[name]}" href="{escape(name)}" media-type="{mime}"' + (' properties="nav"' if name == 'nav.xhtml' else '') + '/>' for name,(mime,_) in assets.items())
        spine = ''.join(f'<itemref idref="{ids[name]}"/>' for name,_ in self.chapters)
        modified = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        opf = (XML + '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id">'
               f'<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="book-id">{self.identifier}</dc:identifier><dc:title>{escape(self.title)}</dc:title><dc:language>{escape(self.language)}</dc:language><meta property="dcterms:modified">{modified}</meta></metadata>'
               f'<manifest>{manifest}</manifest><spine toc="{ids["toc.ncx"]}">{spine}</spine></package>')
        ET.fromstring(opf)
        with ZipFile(output, 'w', compression=ZIP_DEFLATED) as archive:
            archive.writestr('mimetype', b'application/epub+zip', compress_type=ZIP_STORED)
            archive.writestr('META-INF/container.xml', XML + '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles><rootfile full-path="EPUB/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
            archive.writestr('EPUB/content.opf', opf)
            for name,(_,content) in assets.items():
                archive.writestr('EPUB/' + name, content)
