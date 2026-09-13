"""Conservative chapter detection and stable block destinations for navigation."""
import re
import unicodedata
from collections import Counter

NUM = r'[零〇一二三四五六七八九十百千万两0-9０-９]+'
CHINESE = re.compile(rf'^第\s*{NUM}\s*([部篇章节卷])(?:\s|[、:：.．]|$|[^\d\s])')
ENGLISH = re.compile(r'^(part|chapter|section)\s+(?:[0-9]+|[IVXLCDM]+)\b', re.I)
DECIMAL = re.compile(r'^(\d+(?:\.\d+){1,2})\s+\S')
LIST = re.compile(rf'^(?:{NUM}[、．]|\d+\.)\s*\S')
SPECIAL = re.compile(r'^(?:前言|序言|序|自序|译者序|出版说明|引言|绪论|结语|结束语|结论|后记|跋|参考文献|人名索引|附录(?:\s*[A-ZⅠⅡⅢⅣⅤ一二三四五六七八九十0-9]+)?|preface|introduction|conclusion|bibliography|appendix(?:\s+[A-Z0-9])?)$', re.I)
ROLES = re.compile(r'^(?:副?主编|作者|编委|顾问|译者|校对|责任编辑|出版|版权|ISBN)')
PAGE_REFERENCE = re.compile(r'^[.．·…*\s]*[（(]?\s*[0-9０-９]+\s*[）)]?\s*$')
LEADER = re.compile(r'(?:[.．·…]{2,}|\s{2,})\s*\d+\s*$')


def compact(text):
    return re.sub(r'\s+', '', text).lower()


def contents_page(texts):
    return (any(compact(t) in ('目录', '目次', 'contents', 'tableofcontents') for t in texts[:3])
            or sum(bool(LEADER.search(t) or PAGE_REFERENCE.fullmatch(t)) for t in texts) >= 3)


def title_key(text):
    text = unicodedata.normalize('NFKC', text).strip()
    text = re.sub(r'[.·…*\s]*[（(]\s*\d+\s*[）)]\s*$', '', text)
    text = re.sub(r'[.·…]{2,}\s*\d+\s*$', '', text)
    text = re.sub(rf'^(?:第\s*{NUM}\s*[部篇章节卷]|{NUM})[、,.，．\s]*', '', text)
    return re.sub(r'[\W_]+', '', text).lower()


def detect_chapters(job):
    pages = job['pages']
    contents = {p['number'] for p in pages if contents_page([b['text'].strip() for b in p['blocks'] if b['kind'] != 'omit'])}
    contents_titles = {title_key(b['text']) for p in pages if p['number'] in contents for b in p['blocks']
                       if b['kind'] not in ('omit', 'grid') and len(b['text']) <= 100
                       and not PAGE_REFERENCE.fullmatch(b['text'].strip())}
    contents_titles = {t for t in contents_titles if len(t) >= 4}
    repeats = Counter()
    for page in pages:
        repeats.update({compact(b['text']) for b in page['blocks']
                        if b['kind'] == 'heading' and len(b['text'].strip()) <= 100})
    candidates = []
    for page in pages:
        blocks = page['blocks']
        # Printed contents pages are lists of references, not body destinations.
        if page['number'] in contents:
            continue
        for index, block in enumerate(blocks):
            text = block['text'].strip()
            if block['kind'] in ('omit', 'grid') or not text or len(text) > 100 or '\n' in text:
                continue
            normalized = unicodedata.normalize('NFKC', text)
            special = SPECIAL.fullmatch(normalized) or SPECIAL.fullmatch(re.sub(r'\s+', '', normalized))
            if LEADER.search(text) or (ROLES.search(text) and not special) or re.search(r'[。！？!?；;]', text):
                continue
            # Repeated headings usually represent running headers; do not invent a chapter start.
            if repeats[compact(text)] >= 3:
                continue
            cn, en, decimal = CHINESE.match(text), ENGLISH.match(text), DECIMAL.match(text)
            role = None
            reason = ''
            if cn:
                role = {'部':'part', '篇':'part', '卷':'part', '章':'chapter', '节':'section'}[cn[1]]
                reason = '章、节编号'
            elif en:
                role = en[1].lower(); reason = '英文章节编号'
            elif special and block['kind'] == 'heading':
                role = 'chapter'; reason = '常见章节名称'
            elif title_key(text) in contents_titles:
                role = 'chapter'; reason = '与原书目录标题匹配（使用正文位置）'
            elif decimal and block['kind'] == 'heading':
                role = 'decimal'; reason = '多级编号与标题版式'
            elif block['kind'] == 'heading' and LIST.match(text):
                role = 'section'; reason = '编号与标题版式'
            if role:
                candidates.append(dict(page=page['number'], block=index, title='', included=True,
                                       role=role, depth=len(decimal[1].split('.')) if decimal else 1,
                                       reason=reason, _heading=block['kind']=='heading',
                                       _key=title_key(text) if title_key(text) in contents_titles or special else None))
    # When a contents title recurs as a running header, prefer the first actual heading.
    preferred = {}
    for entry in candidates:
        key = entry['_key']
        if key and (key not in preferred or (entry['_heading'] and not preferred[key]['_heading'])):
            preferred[key] = entry
    candidates = [e for e in candidates if not e['_key'] or preferred[e['_key']] is e]
    has_part = any(c['role'] == 'part' for c in candidates)
    for entry in candidates:
        role = entry.pop('role'); depth = entry.pop('depth')
        entry.pop('_heading'); entry.pop('_key')
        entry['level'] = min(3, {'part':1, 'chapter':2 if has_part else 1,
                                'section':3 if has_part else 2, 'decimal':depth}[role])
    return candidates


def resolve_chapters(job):
    """Sort by reading order, filter deleted targets and normalize skipped levels."""
    entries = job.get('toc')
    if entries is None:
        entries = detect_chapters(job)
    targets = {(p['number'], i):(order, b) for order,p in enumerate(job['pages'])
               for i,b in enumerate(p['blocks'])}
    result = []; seen = set()
    for entry in entries:
        key = (entry['page'], entry['block'])
        if not entry.get('included', True) or key not in targets or key in seen:
            continue
        order, block = targets[key]
        if block['kind'] in ('omit', 'grid') or not block['text'].strip():
            continue
        title = entry.get('title', '').strip() or block['text'].strip()
        result.append({**entry, 'title':title[:160], 'level':max(1,min(3,entry['level'])),
                       'anchor':f'chapter-{entry["page"]}-{entry["block"]}', '_order':order})
        seen.add(key)
    result.sort(key=lambda e:(e['_order'], e['block']))
    previous = 0
    for entry in result:
        entry['level'] = min(entry['level'], previous + 1)
        previous = entry['level']
        del entry['_order']
    return result
