#!/usr/bin/env python3
"""BVH -> OpenPose (COCO-18) control image generator. Pure FK, side-view, faces left."""
import sys, math
import numpy as np
from PIL import Image, ImageDraw

def parse_bvh(path):
    toks = open(path).read().split()
    i = 0
    joints=[]  # dict: name,parent,offset,channels
    stack=[]
    nchan=0
    def nxt():
        nonlocal i; v=toks[i]; i+=1; return v
    assert nxt()=='HIERARCHY'
    while i < len(toks):
        t = nxt()
        if t in ('ROOT','JOINT'):
            name = nxt()
            j={'name':name,'parent':stack[-1] if stack else -1,'offset':np.zeros(3),'channels':[],'ci':[]}
            joints.append(j); idx=len(joints)-1
            assert nxt()=='{'
            stack.append(idx)
        elif t=='End':
            nxt()  # 'Site'
            assert nxt()=='{'
            # consume offset
            assert nxt()=='OFFSET'
            for _ in range(3): nxt()
            assert nxt()=='}'
        elif t=='OFFSET':
            j=joints[stack[-1]]
            j['offset']=np.array([float(nxt()),float(nxt()),float(nxt())])
        elif t=='CHANNELS':
            n=int(nxt()); j=joints[stack[-1]]
            for _ in range(n):
                ch=nxt(); j['channels'].append(ch); j['ci'].append(nchan); nchan+=1
        elif t=='}':
            stack.pop()
        elif t=='MOTION':
            break
    assert nxt()=='Frames:'
    nframes=int(nxt())
    assert nxt()=='Frame'; assert nxt()=='Time:'
    ftime=float(nxt())
    motion=[]
    for f in range(nframes):
        row=[float(nxt()) for _ in range(nchan)]
        motion.append(row)
    return joints, motion, nchan

def rotmat(axis,deg):
    a=math.radians(deg); c,s=math.cos(a),math.sin(a)
    if axis=='X': return np.array([[1,0,0],[0,c,-s],[0,s,c]])
    if axis=='Y': return np.array([[c,0,s],[0,1,0],[-s,0,c]])
    return np.array([[c,-s,0],[s,c,0],[0,0,1]])

def fk(joints, frame):
    """return dict name->world position (3,)"""
    W=[None]*len(joints)
    pos={}
    for idx,j in enumerate(joints):
        T=np.eye(4); T[:3,3]=j['offset']
        trans=np.zeros(3); R=np.eye(3)
        for ch,ci in zip(j['channels'],j['ci']):
            v=frame[ci]
            if ch=='Xposition': trans[0]=v
            elif ch=='Yposition': trans[1]=v
            elif ch=='Zposition': trans[2]=v
            elif ch=='Xrotation': R=R@rotmat('X',v)
            elif ch=='Yrotation': R=R@rotmat('Y',v)
            elif ch=='Zrotation': R=R@rotmat('Z',v)
        L=np.eye(4); L[:3,:3]=R; L[:3,3]=j['offset']+trans
        Wj = L if j['parent']==-1 else W[j['parent']]@L
        W[idx]=Wj; pos[j['name']]=Wj[:3,3].copy()
    return pos

# COCO-18 keypoint -> CMU joint
KP = ['Head','Neck','RightArm','RightForeArm','RightHand','LeftArm','LeftForeArm','LeftHand',
      'RightUpLeg','RightLeg','RightFoot','LeftUpLeg','LeftLeg','LeftFoot',None,None,None,None]
KP_COLORS=[(255,0,0),(255,85,0),(255,170,0),(255,255,0),(170,255,0),(85,255,0),(0,255,0),
 (0,255,85),(0,255,170),(0,255,255),(0,170,255),(0,85,255),(0,0,255),(85,0,255),
 (170,0,255),(255,0,255),(255,0,170),(255,0,85)]
LIMBS=[(1,2),(1,5),(2,3),(3,4),(5,6),(6,7),(1,8),(8,9),(9,10),(1,11),(11,12),(12,13),(1,0),
       (0,14),(0,15),(14,16),(15,17)]
LIMB_COLORS=KP_COLORS[:len(LIMBS)]

def render(joints, motion, frame_idx, W=512, H=768, flip=False, travel_axis=2, frame_mode='full'):
    pos = fk(joints, motion[frame_idx])
    # build keypoint list (BVH native: Y up, X lateral, Z depth)
    pts=[]
    for k in KP:
        pts.append(None if (k is None or k not in pos) else pos[k])
    # side-view: horizontal=travel_axis, vertical=Y(up). center on hips midpoint
    hip = (pos['LeftUpLeg']+pos['RightUpLeg'])/2.0
    def proj(p):
        x = p[travel_axis]-hip[travel_axis]
        y = p[1]-hip[1]
        if flip: x=-x
        return np.array([x,y])
    P=[proj(p) if p is not None else None for p in pts]
    # --- approximate face keypoints (Nose/Eyes/Ears) from head orientation ---
    if P[0] is not None and P[1] is not None:
        head=P[0]; neck=P[1]
        hs=max(np.linalg.norm(head-neck),1e-6)
        fwd=np.array([-1.0,0.0]) if flip else np.array([1.0,0.0])   # facing = horizontal
        up=np.array([0.0,1.0])                                       # world up (P y is up)
        P[0] =head+fwd*0.45*hs-up*0.18*hs              # Nose: forward & a bit below skull-top
        P[14]=head+fwd*0.26*hs-up*0.05*hs              # REye
        P[15]=head+fwd*0.30*hs+up*0.04*hs              # LEye (slight vertical offset)
        P[16]=head-fwd*0.18*hs+up*0.02*hs              # REar (behind)
        P[17]=head-fwd*0.16*hs+up*0.11*hs              # LEar
    valid=[q for q in P if q is not None]
    ys=[q[1] for q in valid]; xs=[q[0] for q in valid]
    full_span=max(max(ys)-min(ys), 1e-3)
    if frame_mode=='head':
        # close-up on head+face keypoints
        hk=[i for i in [0,1,14,15,16,17] if P[i] is not None]
        bx=[P[i][0] for i in hk]; by=[P[i][1] for i in hk]
        bw=max(max(bx)-min(bx),1e-3); bh=max(max(by)-min(by),1e-3)
        scale=min((0.6*W)/bw, (0.6*H)/bh)
        bcx=(max(bx)+min(bx))/2.0; bcy=(max(by)+min(by))/2.0
        cx,cy=W*0.5, H*0.5
        def to_px(q):
            return (cx+(q[0]-bcx)*scale, cy-(q[1]-bcy)*scale)
    elif frame_mode=='bust':
        # fit the upper-body bbox (head/face/arms/shoulders down to hips) into frame
        ub=[i for i in [0,1,2,3,4,5,6,7,14,15,16,17,8,11] if P[i] is not None]
        bx=[P[i][0] for i in ub]; by=[P[i][1] for i in ub]
        bw=max(max(bx)-min(bx),1e-3); bh=max(max(by)-min(by),1e-3)
        scale=min((0.86*W)/bw, (0.86*H)/bh)
        bcx=(max(bx)+min(bx))/2.0; bcy=(max(by)+min(by))/2.0
        cx,cy=W*0.5, H*0.5
        def to_px(q):
            return (cx+(q[0]-bcx)*scale, cy-(q[1]-bcy)*scale)
    else:
        xspan=max(max(xs)-min(xs),1e-3)
        scale=min((0.80*H)/full_span, (0.90*W)/xspan)   # fit both height & width
        cx0=(max(xs)+min(xs))/2.0
        cx,cy=W*0.5, H*0.52
        def to_px(q):
            return (cx+(q[0]-cx0)*scale, cy-q[1]*scale)
    img=Image.new('RGB',(W,H),(0,0,0)); d=ImageDraw.Draw(img)
    lw=max(4,int(H/110)); r=max(5,int(H/95))
    for (a,b),col in zip(LIMBS,LIMB_COLORS):
        if P[a] is None or P[b] is None: continue
        d.line([to_px(P[a]),to_px(P[b])], fill=col, width=lw)
    for i,q in enumerate(P):
        if q is None: continue
        x,y=to_px(q)
        d.ellipse([x-r,y-r,x+r,y+r], fill=KP_COLORS[i])
    return img

if __name__=='__main__':
    path=sys.argv[1]; out_prefix=sys.argv[2]
    frames=[int(x) for x in sys.argv[3].split(',')] if len(sys.argv)>3 else [40]
    flip = (len(sys.argv)>4 and sys.argv[4]=='flip')
    taxis = int(sys.argv[5]) if len(sys.argv)>5 else 2
    joints, motion, nchan = parse_bvh(path)
    print("joints",len(joints),"frames",len(motion),"chan",nchan)
    for f in frames:
        im=render(joints, motion, f, flip=flip, travel_axis=taxis)
        fn=f"{out_prefix}_f{f:03d}.png"; im.save(fn); print("saved",fn)
