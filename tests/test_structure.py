import math
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET
import cv2
import numpy as np
from PIL import Image, ImageDraw
import pypdfium2 as pdfium
from app.geometry import estimate_skew, rotate_expanded, find_page_quad, rectify, recognize_corrected
from app.structure import reconstruct_structure, grid_cells
from app.export import export_book


def cell(text,x,y,w=80):
    return ([[x,y],[x+w,y],[x+w,y+24],[x,y+24]],text,.98)


def names():
    return [cell(name,100+c*180,120+r*60) for r,row in enumerate([
        ['王丹坤','傅金仲','周同文'],['陈明远','张景中','李文林'],['吴文俊','杨乐','王元']]) for c,name in enumerate(row)]


def transformed(rows,matrix):
    return [(cv2.perspectiveTransform(np.asarray(box,dtype=np.float32)[None],matrix)[0].tolist(),text,score) for box,text,score in rows]


def test_skew_consensus_and_rotation():
    image=Image.new('RGB',(800,600),'white')
    tilted,matrix=rotate_expanded(image,-5)
    rows=transformed(names(),matrix)
    assert abs(estimate_skew(rows)-5)<.01
    corrected,undo=rotate_expanded(tilted,estimate_skew(rows))
    assert abs(estimate_skew(transformed(rows,undo)))<.01
    assert corrected.width >= image.width and corrected.height>=image.height
    assert estimate_skew([cell('三字名',20,20)]) is None


def test_page_quad_and_perspective_with_text_guard():
    image=Image.new('RGB',(900,1100),(45,45,45))
    quad=np.array([[80,60],[820,100],[840,1030],[40,1040]],dtype=np.float32)
    ImageDraw.Draw(image).polygon([tuple(p) for p in quad],fill='white')
    found=find_page_quad(image,[])
    assert found is not None
    assert np.max(np.linalg.norm(found-quad,axis=1))<8
    corrected,matrix=rectify(image,found)
    mapped=cv2.perspectiveTransform(found[None],matrix)[0]
    assert abs(mapped[0,1]-mapped[1,1])<.01
    assert abs(mapped[0,0]-mapped[3,0])<.01
    assert find_page_quad(image,[cell('保留边缘文字',0,0)]) is None
    assert find_page_quad(Image.new('RGB',(800,1000),'white'),[]) is None


def test_reruns_ocr_after_accepted_correction():
    image=Image.new('RGB',(800,600),'white')
    image,matrix=rotate_expanded(image,-4)
    calls=[]
    def engine(pixels):
        calls.append(pixels.shape)
        return (transformed(names(),matrix) if len(calls)==1 else names()),None
    output,rows,meta=recognize_corrected(image,engine)
    assert len(calls)==2 and abs(meta['deskew_degrees']-4)<.01
    assert rows==names()
    assert np.asarray(meta['matrix']).shape==(3,3)


def test_grid_alignment_and_text_preservation():
    rows=[cell('编委会',260,40)]+names()+[cell('这里是完整的正文段落。',80,360,580)]
    result=reconstruct_structure(rows,800,1000)
    grids=[b for b in result if b['kind']=='grid']
    assert len(grids)==1
    assert grid_cells(grids[0]['text'])==[['王丹坤','傅金仲','周同文'],['陈明远','张景中','李文林'],['吴文俊','杨乐','王元']]
    assert len(grids[0]['lines'])==9
    assert result[-1]['text']=='这里是完整的正文段落。'
    # Paragraphs in two columns must not be mistaken for short-name cells.
    prose=[cell('这是一句正文，不是姓名。',x,y,230) for y in (100,150,200) for x in (40,420)]
    assert not any(b['kind']=='grid' for b in reconstruct_structure(prose,800,1000))


def test_ocr_combined_names_and_misaligned_rows():
    rows=[cell('王丹坤 傅金仲 周同文',100,100,500),cell('陈明远 张景中 李文林',100,160,500)]
    assert reconstruct_structure(rows,800,1000)[0]['kind']=='grid'
    assert grid_cells('A\tB\nC')==[['A','B'],['C','']]


def test_export_real_grid_and_edited_cell(tmp_path):
    blocks=reconstruct_structure(names(),800,1000)
    blocks[0]['text']=blocks[0]['text'].replace('王丹坤','修改姓名')
    job=dict(title='名单布局验证',pages=[dict(number=1,blocks=blocks)])
    with ZipFile(export_book(job,tmp_path,'epub')) as archive:
        text=archive.read('EPUB/page-1.xhtml').decode()
        root=ET.fromstring(text)
        ns={'h':'http://www.w3.org/1999/xhtml'}
        assert len(root.findall('.//h:tr',ns))==3
        assert len(root.findall('.//h:td',ns))==9
        assert '修改姓名' in text and '王丹坤' not in text
        assert 'position:absolute' not in text
    with pdfium.PdfDocument(str(export_book(job,tmp_path,'pdf'))) as doc:
        page=doc[0];textpage=page.get_textpage();text=textpage.get_text_range()
        assert '修改姓名' in text and '李文林' in text
        # Cell baselines must align despite their original coordinates.
        positions=[]
        for needle in ('修改姓名','傅金仲','周同文'):
            index=text.index(needle);positions.append(textpage.get_charbox(index))
        assert max(p[1] for p in positions)-min(p[1] for p in positions)<1
        assert positions[0][0]<positions[1][0]<positions[2][0]
        textpage.close();page.close()


def test_missing_cell_and_single_row_names():
    rows=names();rows=[r for r in rows if r[1]!='张景中']
    result=reconstruct_structure(rows,800,1000)
    assert len(result)==1 and result[0]['kind']=='grid'
    assert grid_cells(result[0]['text'])[1]==['陈明远','','李文林']
    assert result[0]['missing_cells']
    assert reconstruct_structure(names()[:3],800,1000)[0]['kind']=='grid'


def test_rebuild_preserves_old_edits_and_scan_view(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    import json
    monkeypatch.setattr(main,'DATA',tmp_path)
    monkeypatch.setattr(main,'jobs',{})
    class Queue:
        def submit(self,*args): pass
    monkeypatch.setattr(main,'executor',Queue())
    directory=tmp_path/'old';directory.mkdir()
    (directory/'source.pdf').write_bytes(b'original PDF source')
    Image.new('RGB',(80,100),'white').save(directory/'page-1.jpg')
    Image.new('RGB',(80,100),'red').save(directory/'raw-1.jpg')
    job=dict(id='old',title='已校对',status='ready',start=1,end=1,dpi=180,total=1,source_pages=1,
             pages=[dict(number=1,blocks=[dict(kind='grid',text='校对姓名\t第二位')])])
    main.jobs['old']=job;main.persist(job)
    old_file=(directory/'job.json').read_bytes()
    client=TestClient(main.app)
    result=client.post('/api/jobs/old/rebuild');assert result.status_code==202
    new=result.json();assert new['id']!='old' and new['correct_scan'] and new['pages']==[]
    assert (directory/'job.json').read_bytes()==old_file
    assert (tmp_path/new['id']/'source.pdf').read_bytes()==b'original PDF source'
    assert client.get('/api/jobs/old/pages/1?original=true').content==(directory/'raw-1.jpg').read_bytes()
    assert client.get('/api/jobs/old/pages/1').content==(directory/'page-1.jpg').read_bytes()
    assert client.put('/api/jobs/old',json={'title':'已校对','pages':job['pages']}).status_code==200
