import copy
from zipfile import ZipFile
from xml.etree import ElementTree as ET
import pypdfium2 as pdfium
from app.chapters import detect_chapters, resolve_chapters
from app.export import export_book


def block(text, kind='heading'):
    return dict(text=text, kind=kind, confidence=.99)


def test_detection_excludes_contents_headers_authors_and_body():
    job={'pages':[
        {'number':1,'blocks':[block('目 录'),block('第一章 引言 .... 3'),block('第二章 方法 .... 8')]},
        {'number':2,'blocks':[block('主编：张三'),block('张三\t李四','grid'),block('第一章 引言'),block('这是一段普通正文。','paragraph'),block('第一节 背景'),block('1.1 方法'),block('页眉')]},
        {'number':3,'blocks':[block('页眉'),block('第二章 实验')]},
        {'number':4,'blocks':[block('页眉'),block('Appendix A')]}]}
    result=resolve_chapters(job)
    assert [e['title'] for e in result]==['第一章 引言','第一节 背景','1.1 方法','第二章 实验','Appendix A']
    assert [e['level'] for e in result]==[1,2,2,1,1]
    assert 'toc' not in job


def test_parts_levels_and_live_title_resolution():
    job={'pages':[{'number':8,'blocks':[block('第一篇 基础'),block('第一章 导论'),block('第一节 背景')]}]}
    job['toc']=detect_chapters(job)
    assert [e['level'] for e in resolve_chapters(job)]==[1,2,3]
    job['pages'][0]['blocks'][1]['text']='第一章 修正后的标题'
    assert resolve_chapters(job)[1]['title']=='第一章 修正后的标题'
    job['toc'][0]['included']=False
    assert [e['level'] for e in resolve_chapters(job)]==[1,2]
    job['toc'][1]['title']='自定义目录名'
    job['pages'][0]['blocks'][2]['kind']='omit'
    assert [e['title'] for e in resolve_chapters(job)]==['自定义目录名']
    job['toc']=[]
    assert not resolve_chapters(job)


def test_nested_epub_and_pdf_destinations(tmp_path):
    job={'title':'章节目录测试','pages':[
        {'number':10,'blocks':[block('第一章 起点 & 思考'),block('正文内容用于分页。'*750,'paragraph'),block('第一节 方法'),block('节正文。','paragraph')]},
        {'number':11,'blocks':[block('第二章 结论'),block('最后正文。','paragraph')]}]}
    chapters=resolve_chapters(job)
    epub=export_book(job,tmp_path,'epub')
    with ZipFile(epub) as z:
        ns={'h':'http://www.w3.org/1999/xhtml','n':'http://www.daisy.org/z3986/2005/ncx/'}
        nav=ET.fromstring(z.read('EPUB/nav.xhtml'))
        links=nav.findall('.//h:a',ns)
        assert [a.text for a in links]==[e['title'] for e in chapters]
        assert len(nav.findall('.//h:ol/h:li/h:ol/h:li',ns))==1
        for a in links:
            file,anchor=a.attrib['href'].split('#')
            root=ET.fromstring(z.read('EPUB/'+file))
            assert any(n.attrib.get('id')==anchor for n in root.iter())
        ncx=ET.fromstring(z.read('EPUB/toc.ncx'))
        assert len(ncx.findall('.//n:navPoint/n:navPoint',ns))==1
        assert len(ET.fromstring(z.read('EPUB/content.opf')).findall('{*}spine/{*}itemref'))==2
    pdf=export_book(job,tmp_path,'pdf')
    with pdfium.PdfDocument(str(pdf)) as doc:
        bookmarks=list(doc.get_toc())
        assert [b.get_title() for b in bookmarks]==[e['title'] for e in chapters]
        assert [b.level for b in bookmarks]==[0,1,0]
        assert bookmarks[1].get_dest().get_index()>bookmarks[0].get_dest().get_index()
        for b in bookmarks:
            page=doc[b.get_dest().get_index()];textpage=page.get_textpage()
            assert b.get_title() in textpage.get_text_range()
            textpage.close();page.close()
        first=doc[0];text=first.get_textpage();assert '目录' in text.get_text_range();text.close();first.close()


def test_toc_api_preserves_manual_entries_and_revision(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    job=dict(id='chapters',status='ready',title='目录测试',pages=[dict(number=2,blocks=[block('第一章 测试')])])
    monkeypatch.setattr(main,'jobs',{'chapters':job});monkeypatch.setattr(main,'DATA',tmp_path)
    (tmp_path/'chapters').mkdir();client=TestClient(main.app)
    toc=client.post('/api/jobs/chapters/chapters/detect').json()['toc']
    assert 'toc' not in job
    payload=dict(title=job['title'],pages=job['pages'],toc=toc,revision=0)
    assert client.put('/api/jobs/chapters',json=payload).status_code==200
    assert job['toc'][0]['level']==1
    payload['revision']=1;payload['toc']=[{**toc[0],'block':99}]
    before=copy.deepcopy(job)
    assert client.put('/api/jobs/chapters',json=payload).status_code==400
    assert job==before
    payload['toc']=toc;payload['revision']=0
    assert client.put('/api/jobs/chapters',json=payload).status_code==409


def test_split_printed_contents_matches_body_and_deduplicates_headers():
    job={'pages':[
        {'number':1,'blocks':[block('一、关于发明的一般考察','paragraph'),block('..( 4 )','paragraph'),
                              block('二、逻辑与机遇','paragraph'),block('...(20)','paragraph'),
                              block('附录 I','paragraph'),block('.( 30 )','paragraph')]},
        {'number':5,'blocks':[block('关于发明的一般考察'),block('正文内容。','paragraph')]},
        {'number':6,'blocks':[block('一、关于发明的一般考察','paragraph'),block('接续正文。','paragraph')]},
        {'number':7,'blocks':[block('一，关于发明的一般考察','paragraph')]},
        {'number':21,'blocks':[block('二逻辑与机遇')]},
        {'number':31,'blocks':[block('附录Ⅰ')]}]}
    result=resolve_chapters(job)
    assert [e['page'] for e in result]==[5,21,31]
    assert [e['title'] for e in result]==['关于发明的一般考察','二逻辑与机遇','附录Ⅰ']
