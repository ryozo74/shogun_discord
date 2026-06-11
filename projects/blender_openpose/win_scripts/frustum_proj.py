import socket, json
def call(req, timeout=120):
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
import bpy, mathutils, math, json, traceback
from bpy_extras.object_utils import world_to_camera_view
sc=bpy.context.scene
try:
    sc.render.resolution_x=1280; sc.render.resolution_y=720
    arm=bpy.data.objects['cmu_sprint']; sc.frame_set(140); bpy.context.view_layer.update()
    cam=sc.camera; cam.data.lens=50; cam.data.sensor_fit='VERTICAL'; cam.data.sensor_height=24.0
    # all bone heads world
    pts={pb.name:(arm.matrix_world@pb.head) for pb in arm.pose.bones}
    keys=['Head','Neck','LeftFoot','RightFoot','LeftHand','RightHand','Hips','LeftUpLeg','RightUpLeg']
    Ps=[pts[k] for k in keys if k in pts]
    C=sum(Ps,mathutils.Vector())/len(Ps)
    ev=max(p.z for p in Ps)-min(p.z for p in Ps); eh=max(p.y for p in Ps)-min(p.y for p in Ps)
    tv=math.tan(math.atan(12.0/50.0)); th=tv*(1280/720)
    dist=max((ev/2)/tv,(eh/2)/th)/0.82
    loc=C+mathutils.Vector((dist,0,0)); rot=(C-loc).to_track_quat('-Z','Y')
    cam.matrix_world=mathutils.Matrix.Translation(loc)@rot.to_matrix().to_4x4()
    bpy.context.view_layer.update()
    # project every bone head+tail
    proj={}
    for pb in arm.pose.bones:
        h=world_to_camera_view(sc,cam,arm.matrix_world@pb.head)
        t=world_to_camera_view(sc,cam,arm.matrix_world@pb.tail)
        proj[pb.name]={'h':[round(h.x,4),round(h.y,4)],'t':[round(t.x,4),round(t.y,4)],'parent':pb.parent.name if pb.parent else None}
    open(r"C:\Users\bokan.DC1\AppData\Local\Temp\proj.json","w").write(json.dumps(proj))
    cuv=world_to_camera_view(sc,cam,C)
    # ---- create 3D frustum visualization ----
    old=bpy.data.objects.get('cam_frustum')
    if old: bpy.data.objects.remove(old,do_unlink=True)
    dg=bpy.context.evaluated_depsgraph_get()
    frame=cam.data.view_frame(scene=sc)               # 4 corners in cam local at focal
    mw=cam.matrix_world
    far=8.0
    corners=[mw@(c*(far/abs(c.z))) for c in frame]    # project corners to far plane
    apex=mw.translation
    verts=[apex]+corners
    edges=[(0,1),(0,2),(0,3),(0,4),(1,2),(2,3),(3,4),(4,1)]
    me=bpy.data.meshes.new('cam_frustum'); me.from_pydata(verts,edges,[]); me.update()
    fo=bpy.data.objects.new('cam_frustum',me); sc.collection.objects.link(fo)
    fo.display_type='WIRE'; fo.show_in_front=True
    print("C_uv=(%.2f,%.2f) dist=%.2f bones=%d frustum_created"%(cuv.x,cuv.y,dist,len(proj)))
except Exception:
    print("PYERR", traceback.format_exc())
'''
print(call({"type":"execute_code","params":{"code":setup}}))
