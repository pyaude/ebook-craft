import copy
import json
import logging
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pypdfium2 as pdfium
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .layout import reconstruct
from .geometry import recognize_corrected
from .structure import reconstruct_structure
from .chapters import detect_chapters
from .export import export_book
from .figures import extract_figures, make_figure

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get('PDF_CONVERTER_DATA', ROOT / 'data'))
DATA.mkdir(parents=True, exist_ok=True)
app = FastAPI(title='重页 · 扫描书重排')
executor = ThreadPoolExecutor(max_workers=1)
lock = threading.RLock()
render_lock = threading.Lock()  # PDFium is not thread-safe.
engine = None
jobs = {}
for path in DATA.glob('*/job.json'):
    try:
        job = json.loads(path.read_text())
        if job['status'] in ('queued', 'running'):
            job.update(status='interrupted', message='服务已重启，请重新上传继续识别。')
        jobs[job['id']] = job
    except (ValueError, KeyError):
        logging.warning('Cannot load %s', path)


def persist(job):
    directory = DATA / job['id']
    tmp = directory / 'job.tmp'
    tmp.write_text(json.dumps(job, ensure_ascii=False), encoding='utf-8')
    tmp.replace(directory / 'job.json')


def get_job(job_id):
    if job_id not in jobs:
        raise HTTPException(404, '任务不存在')
    return jobs[job_id]


def process(job_id):
    global engine
    job = jobs[job_id]
    directory = DATA / job_id
    try:
        with lock:
            if job['status'] == 'cancelled':
                return
            job.update(status='running', message='正在加载本地 OCR 模型…')
            persist(job)
        if engine is None:
            from rapidocr_onnxruntime import RapidOCR
            engine = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=2)
        for number in range(job['start'], job['end'] + 1):
            with lock:
                if job['status'] == 'cancelled':
                    return
                job['message'] = f"正在识别第 {number} 页 / {job['end']} 页"
            with render_lock:
                with pdfium.PdfDocument(str(directory / 'source.pdf')) as doc:
                    page = doc[number - 1]
                    scale = min(job['dpi'] / 72, 3000 / max(page.get_size()))
                    bitmap = page.render(scale=scale)
                    image = bitmap.to_pil().convert('RGB')
                    bitmap.close()
                    page.close()
            image.save(directory / f'raw-{number}.jpg', quality=95)
            image, rows, correction = recognize_corrected(image, engine, job.get('correct_scan', True))
            image.save(directory / f'page-{number}.jpg', quality=95)
            blocks = reconstruct_structure(rows, *image.size)
            figures = extract_figures(image, blocks, directory, number)
            result = dict(number=number, width=image.width, height=image.height,
                          blocks=blocks, figures=figures, figures_detected=True,
                          correction=correction, structure_version=1,
                          retain_original=not bool(blocks or figures))
            with lock:
                if job['status'] == 'cancelled':
                    return
                job['pages'].append(result)
                job['completed'] += 1
                persist(job)
        with lock:
            job['toc'] = detect_chapters(job)
            job.update(status='ready', message='识别完成，已生成章节目录，请校对后导出。')
            persist(job)
    except Exception as exc:
        logging.exception('OCR failed')
        with lock:
            job.update(status='error', message=f'识别失败：{exc}')
            persist(job)


@app.get('/api/jobs')
def list_jobs():
    with lock:
        return [{k: v for k, v in j.items() if k != 'pages'} for j in reversed(list(jobs.values()))]


@app.post('/api/jobs', status_code=202)
async def create_job(file: UploadFile = File(...), start: int = Form(1), end: int = Form(0), dpi: int = Form(180), correct_scan: bool = Form(True)):
    if start < 1 or end < 0 or dpi not in (144, 180, 216):
        raise HTTPException(400, '页码或精度无效')
    with lock:
        if sum(j['status'] in ('queued', 'running') for j in jobs.values()) >= 3:
            raise HTTPException(429, '最多同时排队 3 个任务')
    job_id = uuid.uuid4().hex
    directory = DATA / job_id
    directory.mkdir()
    try:
        size = 0
        with (directory / 'source.pdf').open('wb') as stream:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > 300 * 1024 * 1024:
                    raise ValueError('文件不能超过 300 MB')
                stream.write(chunk)
        with render_lock:
            with pdfium.PdfDocument(str(directory / 'source.pdf')) as doc:
                count = len(doc)
        end = end or count
        if not 1 <= start <= end <= count or end - start + 1 > 500:
            raise ValueError('页码范围无效，单次最多处理 500 页')
    except Exception as exc:
        import shutil
        shutil.rmtree(directory)
        raise HTTPException(400, f'无法读取 PDF：{exc}') from exc
    finally:
        await file.close()
    job = dict(id=job_id, title=Path(file.filename or '未命名书籍').stem, status='queued',
               message='等待识别…', start=start, end=end, dpi=dpi, total=end-start+1,
               source_pages=count, completed=0, pages=[], correct_scan=correct_scan)
    with lock:
        jobs[job_id] = job
        persist(job)
    executor.submit(process, job_id)
    return job


@app.get('/api/jobs/{job_id}')
def detail(job_id: str):
    with lock:
        return copy.deepcopy(get_job(job_id))


@app.post('/api/jobs/{job_id}/cancel')
def cancel(job_id: str):
    with lock:
        job = get_job(job_id)
        if job['status'] in ('queued', 'running'):
            job.update(status='cancelled', message='任务已取消；已识别页面可校对和导出。')
            persist(job)
    return {'ok': True}



@app.post('/api/jobs/{job_id}/rebuild', status_code=202)
def rebuild(job_id: str):
    import shutil
    with lock:
        original = get_job(job_id)
        if original['status'] in ('queued', 'running'):
            raise HTTPException(409, '请等待当前识别完成')
        if sum(j['status'] in ('queued', 'running') for j in jobs.values()) >= 3:
            raise HTTPException(429, '最多同时排队 3 个任务')
        new_id = uuid.uuid4().hex
        directory = DATA / new_id
        directory.mkdir()
        shutil.copy2(DATA / job_id / 'source.pdf', directory / 'source.pdf')
        new_job = {k: original[k] for k in ('start','end','dpi','total','source_pages')}
        new_job.update(id=new_id, title=original['title'] + ' · 结构恢复',
                       status='queued', message='等待校正与结构恢复…', completed=0,
                       pages=[], correct_scan=True)
        jobs[new_id] = new_job
        persist(new_job)
        executor.submit(process, new_id)
        return copy.deepcopy(new_job)


class BlockEdit(BaseModel):
    kind: str = Field(pattern='^(paragraph|heading|grid|omit)$')
    text: str = Field(max_length=100000)


class FigureEdit(BaseModel):
    id: str
    included: bool = True
    before_block: int = Field(ge=0)
    caption: str = Field(default="", max_length=1000)


class PageEdit(BaseModel):
    number: int
    retain_original: bool = False
    blocks: list[BlockEdit] = Field(max_length=5000)
    figures: list[FigureEdit] | None = Field(default=None, max_length=100)


class TocEntry(BaseModel):
    page: int = Field(ge=1)
    block: int = Field(ge=0)
    title: str = Field(default='', max_length=160)
    level: int = Field(ge=1, le=3)
    included: bool = True


class BookEdit(BaseModel):
    toc: list[TocEntry] | None = Field(default=None, max_length=2000)
    revision: int | None = None
    title: str = Field(min_length=1, max_length=300)
    pages: list[PageEdit] = Field(max_length=500)


@app.put('/api/jobs/{job_id}')
def save(job_id: str, edit: BookEdit):
    with lock:
        job = get_job(job_id)
        if job['status'] in ('running', 'queued'):
            raise HTTPException(409, '请等待识别完成后校对')
        if edit.revision is not None and edit.revision != job.get('revision',0):
            raise HTTPException(409, '内容已被其他操作更新，请重新打开任务后校对')
        if [p.number for p in edit.pages] != [p['number'] for p in job['pages']]:
            raise HTTPException(400, '页面不匹配，请刷新')
        for current, revised in zip(job['pages'], edit.pages):
            if len(current['blocks']) != len(revised.blocks):
                raise HTTPException(400, '段落数量不匹配')
            if revised.figures is not None:
                if [f.id for f in revised.figures] != [f['id'] for f in current.get('figures', [])]:
                    raise HTTPException(409, '插图已变更，请重新打开任务')
                if any(f.before_block > len(current['blocks']) for f in revised.figures):
                    raise HTTPException(400, '插图位置超出段落范围')
        if edit.toc is not None:
            targets = {(p['number'], i) for p in job['pages'] for i in range(len(p['blocks']))}
            keys = [(e.page, e.block) for e in edit.toc]
            if len(keys) != len(set(keys)) or any(k not in targets for k in keys):
                raise HTTPException(400, '目录目标不存在或重复')
            job['toc'] = [e.model_dump() for e in edit.toc]
        job['title'] = edit.title
        for current, revised in zip(job['pages'], edit.pages):
            current['retain_original'] = revised.retain_original
            if revised.figures is not None:
                for figure, new in zip(current.get('figures', []), revised.figures):
                    figure.update(included=new.included, before_block=new.before_block, caption=new.caption)
            for block, new in zip(current['blocks'], revised.blocks):
                block.update(kind=new.kind, text=new.text)
        job['revision'] = job.get('revision', 0) + 1
        persist(job)
    return {'ok': True, 'revision': job['revision']}


@app.get('/api/jobs/{job_id}/pages/{number}')
def page_image(job_id: str, number: int, original: bool = False):
    with lock:
        job = get_job(job_id)
        if number not in [p['number'] for p in job['pages']]:
            raise HTTPException(404, '页面未生成')
    directory = DATA / job_id
    raw = directory / f'raw-{number}.jpg'
    return FileResponse(raw if original and raw.exists() else directory / f'page-{number}.jpg')



def editable_page(job_id, number):
    job = get_job(job_id)
    if job['status'] in ('running', 'queued'):
        raise HTTPException(409, '请等待识别完成')
    page = next((p for p in job['pages'] if p['number'] == number), None)
    if page is None:
        raise HTTPException(404, '页面未生成')
    return job, page


@app.post('/api/jobs/{job_id}/pages/{number}/figures/detect')
def detect_page_figures(job_id: str, number: int):
    from PIL import Image
    with lock:
        job, page = editable_page(job_id, number)
        directory = DATA / job_id
        # Repeated requests preserve edits and existing figure IDs.
        if not page.get('figures_detected'):
            with Image.open(directory / f'page-{number}.jpg') as image:
                page['figures'] = page.get('figures', []) + extract_figures(image, page['blocks'], directory, number, limit=100-len(page.get('figures', [])))
            page['figures_detected'] = True
            persist(job)
        return copy.deepcopy(page)


class CropOptions(BaseModel):
    bbox: list[int] = Field(min_length=4, max_length=4)


@app.post('/api/jobs/{job_id}/pages/{number}/figures')
def crop_page_figure(job_id: str, number: int, crop: CropOptions):
    from PIL import Image
    with lock:
        job, page = editable_page(job_id, number)
        if len(page.get('figures', [])) >= 100:
            raise HTTPException(400, '单页最多保留 100 张插图')
        directory = DATA / job_id
        with Image.open(directory / f'page-{number}.jpg') as image:
            x, y, r, b = crop.bbox
            if not (0 <= x < r <= image.width and 0 <= y < b <= image.height) or min(r-x,b-y) < 10:
                raise HTTPException(400, '裁切框必须在原页内，宽高至少 10 像素')
            figure = make_figure(image, crop.bbox, page['blocks'], directory, number, 'manual')
        page.setdefault('figures', []).append(figure)
        persist(job)
        return copy.deepcopy(page)


@app.get('/api/jobs/{job_id}/pages/{number}/figures/{figure_id}')
def figure_image(job_id: str, number: int, figure_id: str):
    with lock:
        job = get_job(job_id)
        page = next((p for p in job['pages'] if p['number'] == number), None)
        figure = next((f for f in (page or {}).get('figures', []) if f['id'] == figure_id), None)
        if figure is None:
            raise HTTPException(404, '插图不存在')
        return FileResponse(DATA / job_id / figure['file'], media_type='image/png')


@app.post('/api/jobs/{job_id}/chapters/detect')
def detect_toc(job_id: str):
    # Preview only: explicit saving preserves manual edits and other task revisions.
    with lock:
        job = get_job(job_id)
        if job['status'] in ('queued', 'running'):
            raise HTTPException(409, '请等待识别完成')
        return {'toc': detect_chapters(job)}


class ExportOptions(BaseModel):
    format: str = Field(pattern='^(pdf|epub)$')
    font_size: int = Field(default=11, ge=9, le=16)
    leading: float = Field(default=1.8, ge=1.3, le=2.2)
    page_size: str = Field(default='A5', pattern='^(A4|A5)$')
    include_originals: bool = False


@app.post('/api/jobs/{job_id}/export')
def export(job_id: str, options: ExportOptions):
    # Serialize writes to fixed export filenames and font registration.
    with lock:
        job = get_job(job_id)
        if job['status'] in ('queued', 'running') or not job['pages']:
            raise HTTPException(409, '暂无可导出的页面')
        export_id = uuid.uuid4().hex
        try:
            output = export_book(job, DATA / job_id, options.format, options.font_size,
                                 options.leading, options.page_size, options.include_originals)
            final = output.with_name(f'{export_id}.{options.format}')
            output.replace(final)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    return {'url': f'/api/jobs/{job_id}/downloads/{final.name}'}


@app.get('/api/jobs/{job_id}/downloads/{filename}')
def download(job_id: str, filename: str):
    import re
    get_job(job_id)
    if not re.fullmatch(r'[a-f0-9]{32}\.(pdf|epub)', filename):
        raise HTTPException(404)
    path = DATA / job_id / filename
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, filename=f"{jobs[job_id]['title'][:100]}.{path.suffix[1:]}")


from .proofreader import register_proofreading
register_proofreading(app, jobs, lock, persist)

app.mount('/', StaticFiles(directory=ROOT / 'app/static', html=True), name='web')
