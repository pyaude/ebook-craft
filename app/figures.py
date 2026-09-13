"""Local figure proposals: suppress OCR ink, then group non-text components.

This is a geometric detector, not a semantic layout model. Crops always use the
unmodified source image, keeping labels and fine strokes intact.
"""
import uuid
import cv2
import numpy as np


def detect_regions(image, blocks):
    scale = min(1., 1600 / max(image.size))
    gray = cv2.cvtColor(np.asarray(image.convert('RGB')), cv2.COLOR_RGB2GRAY)
    gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    h, w = gray.shape
    _, ink = cv2.threshold(gray, 210, 255, cv2.THRESH_BINARY_INV)
    text_mask = np.zeros_like(ink)
    for block in blocks:
        for line in block.get('lines', []):
            x, y, r, b = [round(v * scale) for v in line['bbox']]
            cv2.rectangle(text_mask, (max(0,x-3), max(0,y-3)), (min(w-1,r+3), min(h-1,b+3)), 255, -1)
    residual = cv2.bitwise_and(ink, cv2.bitwise_not(text_mask))
    # Scanner borders are not illustrations.
    margin = max(2, round(min(h, w) * .012))
    residual[:margin] = residual[-margin:] = 0
    residual[:, :margin] = residual[:, -margin:] = 0
    grouped = cv2.morphologyEx(residual, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    count, _, stats, _ = cv2.connectedComponentsWithStats(grouped, connectivity=8)
    candidates = []
    for x, y, cw, ch, area in stats[1:count]:
        # Reject rules, isolated glyphs, speckles and mostly-text regions.
        if cw < w * .065 or ch < h * .035 or cw * ch < w * h * .004:
            continue
        if max(cw/ch, ch/cw) > 12 or area < w*h*.0005:
            continue
        roi = residual[y:y+ch, x:x+cw]
        if np.count_nonzero(roi) / (cw*ch) < .035:
            continue
        if np.count_nonzero(text_mask[y:y+ch, x:x+cw]) / (cw*ch) > .45:
            continue
        candidates.append([int(x), int(y), int(x+cw), int(y+ch)])
    # Unite overlapping component bounds (e.g. a framed plot and its contents).
    merged = []
    for box in candidates:
        while True:
            match = next((other for other in merged if min(box[2],other[2]) > max(box[0],other[0]) and min(box[3],other[3]) > max(box[1],other[1])), None)
            if match is None:
                break
            merged.remove(match)
            box = [min(box[0],match[0]), min(box[1],match[1]), max(box[2],match[2]), max(box[3],match[3])]
        merged.append(box)
    pad = 6 / scale
    return [[max(0, int(x/scale-pad)), max(0, int(y/scale-pad)),
             min(image.width, int(r/scale+pad)), min(image.height, int(b/scale+pad))]
            for x,y,r,b in sorted(merged, key=lambda b: (b[1],b[0]))][:100]


def make_figure(image, box, blocks, directory, number, method='opencv'):
    figure_id = uuid.uuid4().hex
    filename = f'figure-{number}-{figure_id}.png'
    image.crop(tuple(box)).save(directory / filename)
    # Insert before the next lower text block; user can adjust for mixed columns.
    before = len(blocks)
    for i, block in enumerate(blocks):
        lines = block.get('lines', [])
        if lines and min(line['bbox'][1] for line in lines) >= box[3] - 8:
            before = i
            break
    return dict(id=figure_id, file=filename, bbox=box, included=True,
                before_block=before, caption='', method=method)


def extract_figures(image, blocks, directory, number, limit=100):
    return [make_figure(image, box, blocks, directory, number)
            for box in detect_regions(image, blocks)[:max(0, limit)]]


def page_content(page):
    """Shared ordering for both output formats; never delete OCR text implicitly."""
    figures = [f for f in page.get('figures', []) if f.get('included', True)]
    for i in range(len(page['blocks']) + 1):
        for figure in figures:
            if figure['before_block'] == i:
                yield 'figure', figure
        if i < len(page['blocks']):
            yield 'text', page['blocks'][i]
