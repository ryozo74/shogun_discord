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
    # bust-up TARGET bones (upper body)
    BUST=['Head','Neck','Neck1','Spine','Spine1','LowerBack','LeftShoulder','RightShoulder',
          'LeftArm','RightArm','LeftForeArm','RightForeArm','LeftHand','RightHand']
    tp=[]
    for nm in BUST:
        pb=arm.pose.bones.get(nm)
        if pb: tp+=[arm.matrix_world@pb.head, arm.matrix_world@pb.tail]
    xs=[p.x for p in tp]; ys=[p.y for p in tp]; zs=[p.z for p in tp]
    bc=mathutils.Vector(((min(xs)+max(xs))/2,(min(ys)+max(ys))/2,(min(zs)+max(zs))/2))
    ey=max(ys)-min(ys); ez=max(zs)-min(zs)
    cam=sc.camera; cam.data.lens=50; cam.data.sensor_fit='VERTICAL'; cam.data.sensor_height=24.0
    tv=math.tan(math.atan(12.0/50.0)); th=tv*(1280/720); FILL=0.82
    d=max((ez/2)/tv,(ey/2)/th)/FILL
    cam.location=bc+mathutils.Vector((-d,0,0))      # keep FLIPPED side (-X)
    cam.rotation_euler=(bc-cam.location).to_track_quat('-Z','Y').to_euler()
    bpy.context.view_layer.update()
    dg=bpy.context.evaluated_depsgraph_get(); cam_e=cam.evaluated_get(dg)
    KP={'Nose':'Head','Neck':'Neck','RShoulder':'RightArm','RElbow':'RightForeArm','RWrist':'RightHand',
        'LShoulder':'LeftArm','LElbow':'LeftForeArm','LWrist':'LeftHand','RHip':'RightUpLeg','RKnee':'RightLeg',
        'RAnkle':'RightFoot','LHip':'LeftUpLeg','LKnee':'LeftLeg','LAnkle':'LeftFoot'}
    out={}
    for k,b in KP.items():
        pb=arm.pose.bones.get(b)
        if pb:
            uv=world_to_camera_view(sc,cam_e,arm.matrix_world@pb.head); out[k]=[round(uv.x,4),round(uv.y,4)]
    json.dump({'kp':out},open(r"C:\Users\bokan.DC1\AppData\Local\Temp\bustkp.json","w"))
    cuv=world_to_camera_view(sc,cam_e,bc)
    print("BUST framed (flipped side) center_uv=(%.3f,%.3f) d=%.2f"%(cuv.x,cuv.y,d))
except Exception:
    print("PYERR", traceback.format_exc())
'''
print(call({"type":"execute_code","params":{"code":setup}}))
