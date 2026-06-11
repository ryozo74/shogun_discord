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
import bpy, mathutils, math, json, traceback
from bpy_extras.object_utils import world_to_camera_view
sc=bpy.context.scene
try:
    sc.render.resolution_x=1280; sc.render.resolution_y=720
    arm=bpy.data.objects['cmu_sprint']; sc.frame_set(140); bpy.context.view_layer.update()
    # ---- TARGET bones for framing (bust-up: upper body) ----
    TARGET=['Head','Neck','Neck1','Spine','Spine1','LowerBack','LeftShoulder','RightShoulder',
            'LeftArm','RightArm','LeftForeArm','RightForeArm','LeftHand','RightHand']
    FILL=0.80; CU,CV=0.5,0.5
    tp=[]
    for nm in TARGET:
        pb=arm.pose.bones.get(nm)
        if pb: tp+=[arm.matrix_world@pb.head, arm.matrix_world@pb.tail]
    xs=[p.x for p in tp]; ys=[p.y for p in tp]; zs=[p.z for p in tp]
    bc=mathutils.Vector(((min(xs)+max(xs))/2,(min(ys)+max(ys))/2,(min(zs)+max(zs))/2))
    ey=max(ys)-min(ys); ez=max(zs)-min(zs)
    cam=sc.camera; cam.data.lens=50; cam.data.sensor_fit='VERTICAL'; cam.data.sensor_height=24.0
    tv=math.tan(math.atan(12.0/cam.data.lens)); th=tv*(1280/720)
    d=max((ez/2)/tv,(ey/2)/th)/FILL
    cam.location=bc+mathutils.Vector((d,0,0))
    cam.rotation_euler=(bc-cam.location).to_track_quat('-Z','Y').to_euler()
    # offset for non-center CU,CV (pan): shift aim along right/up
    bpy.context.view_layer.update()
    dg=bpy.context.evaluated_depsgraph_get(); cam_e=cam.evaluated_get(dg)
    # export ALL bones projected (evaluated) + mark which are TARGET
    proj={}
    for pb in arm.pose.bones:
        h=world_to_camera_view(sc,cam_e,arm.matrix_world@pb.head)
        t=world_to_camera_view(sc,cam_e,arm.matrix_world@pb.tail)
        proj[pb.name]={'h':[round(h.x,4),round(h.y,4)],'t':[round(t.x,4),round(t.y,4)],
                       'parent':pb.parent.name if pb.parent else None,'target':pb.name in TARGET}
    open(r"C:\Users\bokan.DC1\AppData\Local\Temp\proj3.json","w").write(json.dumps({'bones':proj,'target':TARGET}))
    cuv=world_to_camera_view(sc,cam_e,bc)
    print("TARGET=%d bones, d=%.2f, bbox_center_uv=(%.3f,%.3f)"%(len(TARGET),d,cuv.x,cuv.y))
except Exception:
    print("PYERR", traceback.format_exc())
'''
print(call({"type":"execute_code","params":{"code":setup}}))
