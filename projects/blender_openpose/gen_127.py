#!/usr/bin/env python3
"""Regenerate 127_06 sprint OpenPose control images. Auto-detect travel axis, left-facing, dead-center."""
import sys, numpy as np
from bvh2openpose import parse_bvh, fk, render, KP, KP_COLORS, LIMBS, LIMB_COLORS
from PIL import Image, ImageDraw

BVH = sys.argv[1] if len(sys.argv) > 1 else "bvh/127_06.bvh"
PEAK = int(sys.argv[2]) if len(sys.argv) > 2 else 140

joints, motion, nchan = parse_bvh(BVH)
print(f"joints={len(joints)} frames={len(motion)} chan={nchan}")

# detect travel axis: hip horizontal displacement over the clip (axis 0=X vs 2=Z)
hips = np.array([(fk(joints, motion[f])['LeftUpLeg'] + fk(joints, motion[f])['RightUpLeg']) / 2
                 for f in range(len(motion))])
rng = hips.max(0) - hips.min(0)
taxis = 0 if rng[0] > rng[2] else 2
print(f"hip range X={rng[0]:.1f} Y={rng[1]:.1f} Z={rng[2]:.1f} -> travel_axis={taxis}")


def render_centered(fi, W=512, H=768, flip=True, taxis=taxis):
    """Full-body, dead-center: center the whole-figure bbox on both axes."""
    pos = fk(joints, motion[fi])
    pts = [None if (k is None or k not in pos) else pos[k] for k in KP]
    hip = (pos['LeftUpLeg'] + pos['RightUpLeg']) / 2.0

    def proj(p):
        x = p[taxis] - hip[taxis]; y = p[1] - hip[1]
        if flip: x = -x
        return np.array([x, y])
    P = [proj(p) if p is not None else None for p in pts]
    # face KP from head orientation (same recipe as bvh2openpose.render)
    if P[0] is not None and P[1] is not None:
        head, neck = P[0], P[1]
        hs = max(np.linalg.norm(head - neck), 1e-6)
        fwd = np.array([-1.0, 0.0]) if flip else np.array([1.0, 0.0]); up = np.array([0.0, 1.0])
        P[0] = head + fwd * 0.45 * hs - up * 0.18 * hs
        P[14] = head + fwd * 0.26 * hs - up * 0.05 * hs
        P[15] = head + fwd * 0.30 * hs + up * 0.04 * hs
        P[16] = head - fwd * 0.18 * hs + up * 0.02 * hs
        P[17] = head - fwd * 0.16 * hs + up * 0.11 * hs
    valid = [q for q in P if q is not None]
    xs = [q[0] for q in valid]; ys = [q[1] for q in valid]
    bw = max(max(xs) - min(xs), 1e-3); bh = max(max(ys) - min(ys), 1e-3)
    scale = min((0.86 * W) / bw, (0.86 * H) / bh)          # fit bbox both ways, 86% fill
    bcx = (max(xs) + min(xs)) / 2.0; bcy = (max(ys) + min(ys)) / 2.0
    cx, cy = W * 0.5, H * 0.5                                # dead-center

    def to_px(q):
        return (cx + (q[0] - bcx) * scale, cy - (q[1] - bcy) * scale)
    img = Image.new('RGB', (W, H), (0, 0, 0)); d = ImageDraw.Draw(img)
    lw = max(4, int(H / 110)); r = max(5, int(H / 95))
    for (a, b), col in zip(LIMBS, LIMB_COLORS):
        if P[a] is None or P[b] is None: continue
        d.line([to_px(P[a]), to_px(P[b])], fill=col, width=lw)
    for i, q in enumerate(P):
        if q is None: continue
        x, y = to_px(q)
        d.ellipse([x - r, y - r, x + r, y + r], fill=KP_COLORS[i])
    return img


# 1) original 'full' (hip-anchored) at peak, for comparison
render(joints, motion, PEAK, flip=True, travel_axis=taxis).save(f"sprint127_full_f{PEAK:03d}.png")
print(f"saved sprint127_full_f{PEAK:03d}.png  (hip-anchored)")
# 2) dead-center full-body at peak
render_centered(PEAK).save(f"sprint127_center_f{PEAK:03d}.png")
print(f"saved sprint127_center_f{PEAK:03d}.png  (dead-center)")
