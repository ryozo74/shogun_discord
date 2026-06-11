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
setup=r'''
import bpy, json, traceback
from bpy_extras.object_utils import world_to_camera_view
sc=bpy.context.scene
try:
    arm=bpy.data.objects['cmu_sprint']; cam=sc.camera
    dg=bpy.context.evaluated_depsgraph_get(); cam_e=cam.evaluated_get(dg)
    proj={}
    for pb in arm.pose.bones:
        h=world_to_camera_view(sc,cam_e,arm.matrix_world@pb.head)
        t=world_to_camera_view(sc,cam_e,arm.matrix_world@pb.tail)
        proj[pb.name]={'h':[round(h.x,4),round(h.y,4)],'t':[round(t.x,4),round(t.y,4)],'parent':pb.parent.name if pb.parent else None}
    open(r"C:\Users\bokan.DC1\AppData\Local\Temp\proj2.json","w").write(json.dumps(proj))
    print("exported %d bones (evaluated cam)"%len(proj))
except Exception:
    print("PYERR", traceback.format_exc())
'''
print(call({"type":"execute_code","params":{"code":setup}}))
