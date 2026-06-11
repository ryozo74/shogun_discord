# Project the SAME 18 world COCO points used by openpose_viz (incl. world-space face KP)
# through the bust camera -> 18 uv. This makes the flat 2D match the 3D geometry exactly.
setup=r'''
import bpy, math, json, traceback
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view
sc=bpy.context.scene
try:
    arm=bpy.data.objects['cmu_sprint']; cam=bpy.data.objects['op_sidecam']; sc.camera=cam
    sc.frame_set(140); bpy.context.view_layer.update()
    KPB={0:'Head',1:'Neck',2:'RightArm',3:'RightForeArm',4:'RightHand',5:'LeftArm',6:'LeftForeArm',
         7:'LeftHand',8:'RightUpLeg',9:'RightLeg',10:'RightFoot',11:'LeftUpLeg',12:'LeftLeg',13:'LeftFoot'}
    pos={}
    for i,bn in KPB.items():
        pb=arm.pose.bones.get(bn)
        if pb: pos[i]=arm.matrix_world@pb.head
    head=pos[0]; neck=pos[1]; hs=max((head-neck).length,1e-4)
    R=(cam.matrix_world.to_3x3()@Vector((1,0,0))).normalized()
    U=(cam.matrix_world.to_3x3()@Vector((0,1,0))).normalized()
    s=-1.0
    pos[0] =head + R*(s*0.45*hs) - U*(0.18*hs)
    pos[14]=head + R*(s*0.26*hs) - U*(0.05*hs)
    pos[15]=head + R*(s*0.30*hs) + U*(0.04*hs)
    pos[16]=head - R*(s*0.18*hs) + U*(0.02*hs)
    pos[17]=head - R*(s*0.16*hs) + U*(0.11*hs)
    dg=bpy.context.evaluated_depsgraph_get(); cam_e=cam.evaluated_get(dg)
    p18=[None]*18
    for i,p in pos.items():
        uv=world_to_camera_view(sc,cam_e,p); p18[i]=[round(uv.x,4),round(uv.y,4)]
    json.dump({'p18':p18},open(r"C:\Users\bokan.DC1\AppData\Local\Temp\op18_bust.json","w"))
    print("p18 exported nose=%s neck=%s"%(p18[0],p18[1]))
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
print(call({"type":"execute_code","params":{"code":setup}}))
