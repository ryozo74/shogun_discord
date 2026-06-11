#!/usr/bin/env python3
"""WSL draw side (rebuilt 2026-06-10): read Blender-camera projected uv (fullkp.json)
-> draw COCO-18 OpenPose skeleton + DSLR grid preview. v is up in uv; image y is down.

Reconstructs the lost pipeline that produced op_fullbody.png / op_fullbody_grid.png.
Consumes win_scripts/fullkp.json (output of win_scripts/fullbody_kp.py via Blender MCP)."""
import sys, json, math
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# COCO-18 (same order/colors/limbs as bvh2openpose.py)
KP_COLORS = [(255,0,0),(255,85,0),(255,170,0),(255,255,0),(170,255,0),(85,255,0),(0,255,0),
 (0,255,85),(0,255,170),(0,255,255),(0,170,255),(0,85,255),(0,0,255),(85,0,255),
 (170,0,255),(255,0,255),(255,0,170),(255,0,85)]
LIMBS = [(1,2),(1,5),(2,3),(3,4),(5,6),(6,7),(1,8),(8,9),(9,10),(1,11),(11,12),(12,13),(1,0),
         (0,14),(0,15),(14,16),(15,17)]
LIMB_COLORS = KP_COLORS[:len(LIMBS)]
# fullkp.json 'kp' name -> COCO index (0..13); 14..17 (eyes/ears) derived from head orientation
KP_NAME = ['Nose','Neck','RShoulder','RElbow','RWrist','LShoulder','LElbow','LWrist',
           'RHip','RKnee','RAnkle','LHip','LKnee','LAnkle']


def build_points(kp, facing_left=True):
    """kp: {name:[u,v]} (v up). returns P[18] of np.array([u,v]) or None."""
    P = [np.array(kp[n]) if n in kp else None for n in KP_NAME] + [None]*4
    if P[0] is not None and P[1] is not None:
        head, neck = P[0], P[1]                       # 'Nose' slot holds the Head-bone projection
        hs = max(np.linalg.norm(head - neck), 1e-6)
        fwd = np.array([-1.0, 0.0]) if facing_left else np.array([1.0, 0.0])
        up = np.array([0.0, 1.0])                     # uv: v is up
        P[0]  = head + fwd*0.45*hs - up*0.18*hs        # Nose
        P[14] = head + fwd*0.26*hs - up*0.05*hs        # REye
        P[15] = head + fwd*0.30*hs + up*0.04*hs        # LEye
        P[16] = head - fwd*0.18*hs + up*0.02*hs        # REar
        P[17] = head - fwd*0.16*hs + up*0.11*hs        # LEar
    return P


def draw_skeleton(P, W=1280, H=720, lw=8, r=9):
    img = Image.new('RGB', (W, H), (0,0,0)); d = ImageDraw.Draw(img)
    def px(q): return (q[0]*W, (1.0-q[1])*H)          # v up -> image y down
    for (a,b),col in zip(LIMBS, LIMB_COLORS):
        if P[a] is None or P[b] is None: continue
        d.line([px(P[a]), px(P[b])], fill=col, width=lw)
    for i,q in enumerate(P):
        if q is None: continue
        x,y = px(q); d.ellipse([x-r,y-r,x+r,y+r], fill=KP_COLORS[i])
    return img, px


def draw_grid(P, W=1280, H=720, caption=""):
    img, px = draw_skeleton(P, W, H)
    d = ImageDraw.Draw(img)
    try: font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
    except Exception: font = ImageFont.load_default()
    # 0.1 grid ticks + labels
    for i in range(11):
        u = i/10.0; x = u*W
        d.line([(x,0),(x,H)], fill=(45,45,45), width=1)
        d.text((x+3,2), f"{u:.1f}", fill=(150,150,150), font=font)
    for i in range(11):
        v = i/10.0; y = (1.0-v)*H
        d.line([(0,y),(W,y)], fill=(45,45,45), width=1)
        d.text((3,y+1), f"{v:.1f}", fill=(150,150,150), font=font)
    # rule-of-thirds (brighter)
    for t in (1/3, 2/3):
        d.line([(t*W,0),(t*W,H)], fill=(120,120,120), width=1)
        d.line([(0,(1-t)*H),(W,(1-t)*H)], fill=(120,120,120), width=1)
    # center cross (0.5,0.5)
    cx,cy = W*0.5, H*0.5
    d.line([(cx-16,cy),(cx+16,cy)], fill=(255,230,0), width=2)
    d.line([(cx,cy-16),(cx,cy+16)], fill=(255,230,0), width=2)
    # bbox of all valid points (orange)
    valid = [q for q in P if q is not None]
    us = [q[0] for q in valid]; vs = [q[1] for q in valid]
    x0,x1 = min(us)*W, max(us)*W; y0,y1 = (1-max(vs))*H, (1-min(vs))*H
    d.rectangle([x0,y0,x1,y1], outline=(255,160,0), width=2)
    d.text((4, H-20), caption, fill=(255,200,80), font=font)
    return img, (min(us),max(us),min(vs),max(vs))


if __name__ == '__main__':
    src = sys.argv[1] if len(sys.argv) > 1 else "win_scripts/fullkp.json"
    out_prefix = sys.argv[2] if len(sys.argv) > 2 else "op_fullbody_recon"
    caption = sys.argv[3] if len(sys.argv) > 3 else "FULL BODY (all bones) center(0.50,0.50) fill H=88% facing LEFT"
    flip = (len(sys.argv) > 4 and sys.argv[4] == 'flip')   # mirror u->1-u (view from opposite side); facing reverses
    data = json.load(open(src))
    if 'p18' in data:
        # 18 COCO points already projected from 3D-correct geometry (incl. world-space face KP).
        # Draw verbatim — no 2D face-recipe (this is the source of truth; matches the 3D viz).
        P = [None if uv is None else np.array([1.0 - uv[0], uv[1]] if flip else uv) for uv in data['p18']]
    else:
        kp = {n: [1.0 - uv[0], uv[1]] for n, uv in data['kp'].items()} if flip else data['kp']
        P = build_points(kp, facing_left=(not flip))
    clean, _ = draw_skeleton(P)
    clean.save(f"{out_prefix}.png"); print(f"saved {out_prefix}.png  (clean 1280x720 black)")
    bbox_uv = None
    grid, bbox_uv = draw_grid(P, caption=caption)
    grid.save(f"{out_prefix}_grid.png"); print(f"saved {out_prefix}_grid.png  (DSLR grid)")
    lo_u, hi_u, lo_v, hi_v = bbox_uv
    print(f"KP bbox u[{lo_u:.2f}..{hi_u:.2f}] center {(lo_u+hi_u)/2:.2f}  v[{lo_v:.2f}..{hi_v:.2f}] height {hi_v-lo_v:.0%}")
