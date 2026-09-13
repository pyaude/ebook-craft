"""Conservative line-to-paragraph reconstruction, preserving OCR provenance."""
import re
from statistics import median


def reconstruct(rows, width, height):
    lines = []
    for box, text, score in rows or []:
        xs, ys = zip(*box)
        lines.append(dict(text=text.strip(), confidence=float(score),
                          bbox=[min(xs), min(ys), max(xs), max(ys)]))
    if not lines:
        return []
    typical = median(max(1, x['bbox'][3] - x['bbox'][1]) for x in lines)
    # Split only when a genuine vertical gutter is visible. Full-width headings remain first.
    left = [x for x in lines if x['bbox'][2] < width * .52]
    right = [x for x in lines if x['bbox'][0] > width * .48]
    two_columns = len(left) >= 5 and len(right) >= 5 and len(left + right) > .8 * len(lines)
    if two_columns:
        wide = [x for x in lines if x not in left and x not in right]
        top = [x for x in wide if x['bbox'][1] < min(y['bbox'][1] for y in left + right)]
        lines = sorted(top, key=lambda x: x['bbox'][1]) + sorted(left, key=lambda x: x['bbox'][1]) + sorted(right, key=lambda x: x['bbox'][1]) + sorted([x for x in wide if x not in top], key=lambda x: x['bbox'][1])
    else:
        lines.sort(key=lambda x: (round(x['bbox'][1] / max(1, typical * .5)), x['bbox'][0]))
    blocks = []
    previous = None
    for line in lines:
        text, box = line['text'], line['bbox']
        if not text:
            continue
        h = box[3] - box[1]
        heading = len(text) < 45 and ((h > typical * 1.3 and box[2] - box[0] < width * .65) or bool(re.match(r'^第[一二三四五六七八九十百\d]+[章节篇]', text)))
        kind = 'heading' if heading else 'paragraph'
        merge = previous is not None and blocks[-1]['kind'] == kind == 'paragraph'
        if merge:
            p = previous['bbox']
            merge = (0 <= box[1] - p[3] < typical * .9 and -typical * 3 <= box[0] - p[0] < typical * .8 and not re.search(r'[。！？.!?:：]$', previous['text']))
        if merge:
            separator = ' ' if re.search(r'[a-zA-Z0-9]$', blocks[-1]['text']) and re.match(r'[a-zA-Z0-9]', text) else ''
            blocks[-1]['text'] += separator + text
            blocks[-1]['confidence'] = min(blocks[-1]['confidence'], line['confidence'])
            blocks[-1]['lines'].append(line)
        else:
            blocks.append(dict(kind=kind, text=text, confidence=line['confidence'], lines=[line]))
        previous = line
    return blocks
