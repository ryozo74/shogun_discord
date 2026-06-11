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
    # frame on ALL bones (full body)
    tp=[]
    for pb in arm.pose.bones: tp+=[arm.matrix_world@pb.head, arm.matrix_world@pb.tail]
    xs=[p.x for p in tp]; ys=[p.y for p in tp]; zs=[p.z for p in tp]
    bc=mathutils.Vector(((min(xs)+max(xs))/2,(min(ys)+max(ys))/2,(min(zs)+max(zs))/2))
    ey=max(ys)-min(ys); ez=max(zs)-min(zs)
    cam=sc.camera; cam.data.lens=50; cam.data.sensor_fit='VERTICAL'; cam.data.sensor_height=24.0
    tv=math.tan(math.atan(12.0/cam.data.lens)); th=tv*(1280/720)
    FILL=0.88
    d=max((ez/2)/tv,(ey/2)/th)/FILL
    cam.location=bc+mathutils.Vector((d,0,0)); cam.rotation_euler=(bc-cam.location).to_track_quat('-Z','Y').to_euler()
    bpy.context.view_layer.update()
    dg=bpy.context.evaluated_depsgraph_get(); cam_e=cam.evaluated_get(dg)
    # COCO-18 keypoint -> CMU bone (head position)
    KP={'Nose':'Head','Neck':'Neck','RShoulder':'RightArm','RElbow':'RightForeArm','RWrist':'RightHand',
        'LShoulder':'LeftArm','LElbow':'LeftForeArm','LWrist':'LeftHand','RHip':'RightUpLeg','RKnee':'RightLeg',
        'RAnkle':'RightFoot','LHip':'LeftUpLeg','LKnee':'LeftLeg','LAnkle':'LeftFoot'}
    out={}
    for k,bn in KP.items():
        pb=arm.pose.bones.get(bn)
        if pb:
            uv=world_to_camera_view(sc,cam_e,arm.matrix_world@pb.head); out[k]=[round(uv.x,4),round(uv.y,4)]
    # all bones for grid skeleton
    allb={}
    for pb in arm.pose.bones:
        h=world_to_camera_view(sc,cam_e,arm.matrix_world@pb.head); t=world_to_camera_view(sc,cam_e,arm.matrix_world@pb.tail)
        allb[pb.name]={'h':[round(h.x,4),round(h.y,4)],'t':[round(t.x,4),round(t.y,4)],'parent':pb.parent.name if pb.parent else None}
    json.dump({'kp':out,'allb':allb},open(r"C:\Users\bokan.DC1\AppData\Local\Temp\fullkp.json","w"))
    cuv=world_to_camera_view(sc,cam_e,bc)
    print("full-body framed d=%.2f center_uv=(%.3f,%.3f) kp=%d"%(d,cuv.x,cuv.y,len(out)))
except Exception:
    print("PYERR", traceback.format_exc())
'''
print(call({"type":"execute_code","params":{"code":setup}}))
