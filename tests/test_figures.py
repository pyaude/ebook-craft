from pathlib import Path
from zipfile import ZipFile
import json
import xml.etree.ElementTree as ET
import numpy as np
import pypdfium2 as pdfium
from PIL import Image, ImageDraw
from fastapi.testclient import TestClient

from app.figures import detect_regions, extract_figures, page_content
from app.export import export_book


def fixture_page():
    image = Image.new('RGB', (800, 1000), 'white')
    draw = ImageDraw.Draw(image)
    blocks = []
    for y, text in [(80, '上方正文'), (760, '下方正文')]:
        draw.rectangle((100,y,690,y+25), fill='black')
        blocks.append(dict(kind='paragraph', text=text, confidence=.99,
                           lines=[dict(bbox=[95,y-3,695,y+28],text=text,confidence=.99)]))
    # A separated illustration with a frame, shaded ground and fine linework.
    draw.rectangle((170,270,630,630), fill=(222,236,245), outline='black', width=3)
    draw.polygon([(180,600),(350,300),(520,600)], fill=(76,132,112))
    draw.line((180,600,620,600), fill='black', width=3)
    return image, blocks


def test_detect_and_crop_without_ocr_mask_damage(tmp_path):
    image, blocks = fixture_page()
    figures = extract_figures(image, blocks, tmp_path, 1)
    assert len(figures) == 1
    figure = figures[0]
    x,y,r,b = figure['bbox']
    assert x <= 170 and y <= 270 and r >= 630 and b >= 630
    assert y > 200 and b < 700
    assert figure['before_block'] == 1
    with Image.open(tmp_path / figure['file']) as crop:
        assert crop.getpixel((350-x,400-y)) == image.getpixel((350,400))


def test_text_blank_noise_and_rules_are_not_figures():
    image, blocks = fixture_page()
    draw = ImageDraw.Draw(image)
    draw.rectangle((160,260,640,640), fill='white')
    draw.line((60,180,720,180), fill='black', width=2)
    rng = np.random.default_rng(1)
    for x,y in rng.integers([20,200],[780,700],size=(80,2)):
        draw.point((int(x),int(y)),fill='black')
    assert detect_regions(image, blocks) == []
    assert detect_regions(Image.new('RGB',(800,1000),'white'), []) == []


def test_two_separate_pictures_and_labels(tmp_path):
    image, blocks = fixture_page()
    draw=ImageDraw.Draw(image)
    draw.rectangle((170,270,630,630), fill='white')
    draw.rectangle((80,300,320,520),fill='navy')
    draw.rectangle((470,300,710,520),fill='green')
    assert len(extract_figures(image, blocks, tmp_path, 1)) == 2


def test_output_images_order_and_exclusion(tmp_path):
    image, blocks = fixture_page()
    figures = extract_figures(image, blocks, tmp_path, 1)
    figures[0]['caption'] = '插图 <1> & 示例'
    page=dict(number=1, blocks=blocks, figures=figures, retain_original=False)
    job=dict(title='插图导出验证', pages=[page])
    assert [kind for kind,_ in page_content(page)] == ['text','figure','text']
    pdf=export_book(job,tmp_path,'pdf')
    with pdfium.PdfDocument(str(pdf)) as doc:
        count=sum(1 for page_obj in doc for obj in page_obj.get_objects() if obj.type==3)
        assert count == 1
    path=export_book(job,tmp_path,'epub')
    with ZipFile(path) as archive:
        text=archive.read('EPUB/page-1.xhtml').decode()
        ET.fromstring(text)
        assert text.index('上方正文') < text.index('<figure>') < text.index('下方正文')
        assert '插图 &lt;1&gt; &amp; 示例' in text
        assert f"EPUB/images/{figures[0]['file']}" in archive.namelist()
    figures[0]['included']=False
    with ZipFile(export_book(job,tmp_path,'epub')) as archive:
        assert '<figure>' not in archive.read('EPUB/page-1.xhtml').decode()
        assert not any(name.endswith('.png') for name in archive.namelist())
    with pdfium.PdfDocument(str(export_book(job,tmp_path,'pdf'))) as doc:
        assert not any(obj.type==3 for p in doc for obj in p.get_objects())


def test_old_job_detect_crop_edit_and_validation(tmp_path, monkeypatch):
    from app import main
    monkeypatch.setattr(main,'DATA',tmp_path)
    monkeypatch.setattr(main,'jobs',{})
    directory=tmp_path/'test'; directory.mkdir()
    image,blocks=fixture_page(); image.save(directory/'page-1.jpg',quality=95)
    main.jobs['test']=dict(id='test',title='旧任务',status='ready',pages=[dict(number=1,blocks=blocks)])
    client=TestClient(main.app)
    base='/api/jobs/test/pages/1/figures'
    response=client.post(base+'/detect'); assert response.status_code==200
    page=response.json(); assert len(page['figures'])==1
    assert client.post(base+'/detect').json()['figures']==page['figures']
    figure=page['figures'][0]
    assert client.get(base+'/'+figure['id']).headers['content-type']=='image/png'
    assert client.get(base+'/nope').status_code==404
    for box in ([0,0,900,1000],[20,20,10,40],[-1,0,200,300],[0,0,2,2]):
        assert client.post(base,json={'bbox':box}).status_code==400
    response=client.post(base,json={'bbox':[160,260,640,640]})
    assert response.status_code==200
    page=response.json(); assert len(page['figures'])==2
    assert page['figures'][1]['method']=='manual'
    figure=page['figures'][0]; figure.update(included=False,before_block=0,caption='说明')
    assert client.put('/api/jobs/test',json={'title':'测试','pages':[page]}).status_code==200
    persisted=json.loads((directory/'job.json').read_text())
    assert persisted['pages'][0]['figures'][0]['included'] is False
    before=json.loads((directory/'job.json').read_text())
    page['figures'][0]['before_block']=999
    assert client.put('/api/jobs/test',json={'title':'错误更改','pages':[page]}).status_code==400
    assert json.loads((directory/'job.json').read_text())==before
    main.jobs['test']['status']='running'
    assert client.post(base+'/detect').status_code==409
