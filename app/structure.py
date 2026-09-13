"""Infer aligned rows/cells; export structure, never raw scan coordinates."""
import re
from statistics import median
from .layout import reconstruct


def _box(row):
    xs,ys=zip(*row[0]);return [min(xs),min(ys),max(xs),max(ys)]


def _split_names(rows):
    result=[]
    for box,text,score in rows:
        parts=re.split(r'\s+',text.strip())
        # OCR sometimes returns a complete names row as one box.
        if 2<=len(parts)<=6 and all(re.fullmatch(r'[\u4e00-\u9fff·]{2,5}',p) for p in parts):
            x,y,r,b=_box((box,text,score));step=(r-x)/len(parts)
            for i,part in enumerate(parts):
                result.append(([[x+i*step,y],[x+(i+1)*step,y],[x+(i+1)*step,b],[x+i*step,b]],part,score))
        else:
            result.append((box,text,score))
    return result


def reconstruct_structure(rows,width,height):
    if not rows:
        return []
    rows=_split_names(rows)
    typical=median(max(1,_box(row)[3]-_box(row)[1]) for row in rows)
    bands=[]
    for row in sorted(rows,key=lambda row: (_box(row)[1],_box(row)[0])):
        cy=(_box(row)[1]+_box(row)[3])/2
        if bands and abs(cy-median((_box(r)[1]+_box(r)[3])/2 for r in bands[-1])) < typical*.65:
            bands[-1].append(row)
        else:
            bands.append([row])
    for band in bands:
        band.sort(key=lambda row:_box(row)[0])
    def candidate(band):
        return 2<=len(band)<=6 and all(len(r[1].strip())<=16 and not re.search(r'[。！？；，,;!?]',r[1]) for r in band) and all(_box(r)[2]-_box(r)[0]<width*.42 for r in band)
    blocks=[]; pending=[];i=0
    def flush():
        if pending:
            blocks.extend(reconstruct(pending,width,height));pending.clear()
    while i<len(bands):
        first=bands[i];group=[first];mapped=[list(range(len(first)))]
        if candidate(first):
            centers=[(_box(r)[0]+_box(r)[2])/2 for r in first]
            j=i+1
            while j<len(bands) and candidate(bands[j]) and len(bands[j])<=len(first):
                band=bands[j]
                gap=min(_box(r)[1] for r in band)-max(_box(r)[3] for r in group[-1])
                assignments=[min(range(len(centers)),key=lambda k:abs((_box(r)[0]+_box(r)[2])/2-centers[k])) for r in band]
                aligned=len(set(assignments))==len(assignments) and all(abs((_box(r)[0]+_box(r)[2])/2-centers[k])<max(typical*1.6,width*.025) for r,k in zip(band,assignments))
                if not aligned or gap>typical*3 or gap<0:
                    break
                group.append(band);mapped.append(assignments);j+=1
        single_names = candidate(first) and (len(first)>=3 or any(re.match(r'^(副?主编|作者|译者)[:：]',r[1]) for r in first))
        if len(group)>=2 or single_names:
            flush()
            flat=[r for band in group for r in band]
            cells=[]
            for band,assignments in zip(group,mapped):
                cells_row=['']*len(first)
                for row,column in zip(band,assignments):
                    cells_row[column]=row[1].strip()
                cells.append(cells_row)
            blocks.append(dict(kind='grid',text='\n'.join('\t'.join(row) for row in cells),
                               confidence=min(float(r[2]) for r in flat),
                               grid_columns=len(first),alignment='center',
                               missing_cells=any(not cell for row in cells for cell in row),
                               lines=[dict(text=r[1],confidence=float(r[2]),bbox=_box(r)) for r in flat]))
            i+=len(group)
        elif len(first)==1 and (re.match(r'^(主编|副主编|编委|委|作者|顾问|译者|校对)[:：]',first[0][1]) or
                               (_box(first[0])[3]-_box(first[0])[1]>=typical*1.15 and _box(first[0])[2]-_box(first[0])[0]<width*.75 and len(first[0][1])<36)):
            flush()
            separate=reconstruct(first,width,height)
            if not re.match(r'^(主编|副主编|编委|委|作者|顾问|译者|校对)[:：]',first[0][1]):
                separate[0]['kind']='heading'
            blocks.extend(separate);i+=1
        else:
            pending.extend(first);i+=1
    flush()
    for block in blocks:
        if block['kind']=='heading':
            x=min(l['bbox'][0] for l in block['lines']);r=max(l['bbox'][2] for l in block['lines'])
            block['alignment']='center' if abs((x+r)/2-width/2)<width*.15 else 'left'
    return blocks


def grid_cells(text):
    """Edited TSV is authoritative, so corrections are reflected in both formats."""
    cells=[line.split('\t') for line in text.splitlines() if line.strip()]
    if not cells:
        return []
    columns=max(map(len,cells))
    if columns>12 or len(cells)>200:
        raise ValueError('网格最多 12 列、200 行，请拆分后导出')
    return [row+['']*(columns-len(row)) for row in cells]
