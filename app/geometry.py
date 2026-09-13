"""Conservative planar page correction before structural reconstruction."""
import math
import cv2
import numpy as np
from PIL import Image


def estimate_skew(rows):
    angles = []
    for box, text, score in rows or []:
        points = np.asarray(box, dtype=float)
        edge = points[1] - points[0]
        if float(score) < .65 or len(text.strip()) < 3 or np.linalg.norm(edge) < 30:
            continue
        angle = math.degrees(math.atan2(edge[1], edge[0]))
        if abs(angle) <= 15:
            angles.append(angle)
    if len(angles) < 4:
        return None
    center = float(np.median(angles))
    inliers = [a for a in angles if abs(a-center) <= 1.2]
    if len(inliers) < max(4, len(angles)*.75):
        return None
    return float(np.median(inliers))


def rotate_expanded(image, angle):
    w,h = image.size
    affine = cv2.getRotationMatrix2D((w/2,h/2), angle, 1)
    cos, sin = abs(affine[0,0]), abs(affine[0,1])
    nw,nh = math.ceil(w*cos+h*sin), math.ceil(h*cos+w*sin)
    affine[0,2] += (nw-w)/2
    affine[1,2] += (nh-h)/2
    result = cv2.warpAffine(np.asarray(image), affine, (nw,nh), flags=cv2.INTER_CUBIC, borderValue=(255,255,255))
    return Image.fromarray(result), np.vstack([affine,[0,0,1]])


def find_page_quad(image, rows):
    scale = min(1.,1200/max(image.size))
    gray = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY)
    small = cv2.resize(gray,None,fx=scale,fy=scale)
    _, mask = cv2.threshold(cv2.GaussianBlur(small,(5,5),0),0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)
    contours,_ = cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    h,w = small.shape
    for contour in sorted(contours,key=cv2.contourArea,reverse=True)[:5]:
        area = cv2.contourArea(contour)/(w*h)
        if not .55 <= area <= .95:
            continue
        approx=cv2.approxPolyDP(contour,.018*cv2.arcLength(contour,True),True)
        if len(approx)!=4 or not cv2.isContourConvex(approx):
            continue
        points=approx.reshape(4,2).astype(np.float32)
        sums=points.sum(axis=1);diff=points[:,1]-points[:,0]
        quad=np.array([points[np.argmin(sums)],points[np.argmin(diff)],points[np.argmax(sums)],points[np.argmax(diff)]],dtype=np.float32)
        if len(np.unique(quad,axis=0))!=4:
            continue
        inside=np.zeros_like(small);cv2.fillConvexPoly(inside,quad.astype(int),255)
        if np.median(small[inside>0])-np.median(small[inside==0]) < 25:
            continue
        full=quad/scale
        # Do not trim off recognized text outside an apparent paper boundary.
        safe=True
        for box,text,score in rows or []:
            if float(score) >= .65 and text.strip():
                for point in box:
                    if cv2.pointPolygonTest(full,tuple(map(float,point)),True) < -6/scale:
                        safe=False
        if safe:
            return full
    return None


def rectify(image, quad):
    tl,tr,br,bl = quad
    w=round(max(np.linalg.norm(tr-tl),np.linalg.norm(br-bl)))
    h=round(max(np.linalg.norm(bl-tl),np.linalg.norm(br-tr)))
    target=np.array([[0,0],[w-1,0],[w-1,h-1],[0,h-1]],dtype=np.float32)
    matrix=cv2.getPerspectiveTransform(quad.astype(np.float32),target)
    result=cv2.warpPerspective(np.asarray(image),matrix,(w,h),flags=cv2.INTER_CUBIC,borderValue=(255,255,255))
    return Image.fromarray(result),matrix


def recognize_corrected(image, engine, enabled=True):
    """OCR is re-run after each accepted transform; boxes are never left stale."""
    rows,_=engine(np.asarray(image))
    metadata=dict(enabled=enabled,perspective=False,deskew_degrees=0.,matrix=np.eye(3).tolist(),notes=[])
    if not enabled:
        metadata['notes'].append('已关闭扫描校正')
        return image,rows,metadata
    matrix=np.eye(3)
    quad=find_page_quad(image,rows)
    if quad is not None:
        image,transform=rectify(image,quad)
        matrix=transform@matrix
        metadata.update(perspective=True,source_quad=quad.tolist())
        rows,_=engine(np.asarray(image))
    else:
        metadata['notes'].append('未找到可靠的纸张四角，未进行透视变换')
    angle=estimate_skew(rows)
    if angle is not None and .25 <= abs(angle) <= 12:
        image,transform=rotate_expanded(image,angle)
        matrix=transform@matrix
        metadata['deskew_degrees']=round(angle,3)
        rows,_=engine(np.asarray(image))
    elif angle is None or abs(angle)>12:
        metadata['notes'].append('文字方向证据不足或倾斜过大，未自动旋转')
    metadata['matrix']=matrix.tolist()
    metadata['notes'].append('仅校正平面倾斜与透视，不进行书脊曲面展平')
    return image,rows,metadata
