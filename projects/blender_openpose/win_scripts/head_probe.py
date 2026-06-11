setup=r'''
import bpy, traceback
from mathutils import Vector
sc=bpy.context.scene
try:
    arm=bpy.data.objects['cmu_sprint']; sc.frame_set(140); bpy.context.view_layer.update()
    def info(bn):
        pb=arm.pose.bones.get(bn)
        if not pb: return None
        mw=arm.matrix_world
        h=mw@pb.head; t=mw@pb.tail
        M=(mw.to_3x3()@pb.matrix.to_3x3())
        ax=lambda c: tuple(round(v,3) for v in M.col[c].normalized())
        return {'head':[round(v,3) for v in h],'tail':[round(v,3) for v in t],
                'x':ax(0),'y':ax(1),'z':ax(2),'len':round((t-h).length,3)}
    out={}
    for b in ['Head','Neck','Neck1','LeftUpLeg','RightUpLeg','LeftArm','RightArm','LowerBack','Spine1']:
        out[b]=info(b)
    # body axes
    L=Vector(out['LeftUpLeg']['head']); Rh=Vector(out['RightUpLeg']['head'])
    leftright=(L-Rh).normalized()
    up=Vector((0,0,1))
    facing=up.cross(leftright).normalized()   # forward = up x (L-R)
    print("FACING(up x (L-R)) =", [round(v,3) for v in facing])
    print("L-R(hip) =", [round(v,3) for v in leftright])
    import json
    print(json.dumps(out))
except Exception:
    print("PYERR", traceback.format_exc())
'''
import socket, json
def call(req, timeout=90):
    s=socket.socket(socket.AF_INET,socket.SOCK_STREAM); s.settimeout(timeout)
    s.connect(("127.0.0.1",9876)); s.sendall(json.dumps(req).encode())
    buf=bytearray()
    try:
        while True:
            c=s.recv(8192)
            if not c: break
            buf.extend(c)
            try: json.loads(bytes(buf).decode("utf-8").split("\0")[0]); break
            except: continue
    except socket.timeout: pass
    s.close(); return bytes(buf).decode("utf-8","replace").split("\0")[0]
r=call({"type":"execute_code","params":{"code":setup}})
print(r)
