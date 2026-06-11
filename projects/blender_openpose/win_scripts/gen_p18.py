# Reproducible OpenPose p18 generator: frames full-body AND bust from the -X side (facing RIGHT),
# face KP derived from the real Head-bone orientation (not hand-tuned), projects 18 COCO pts.
# Outputs op18_full.json + op18_bust.json. Deterministic, frame/orientation-agnostic.
setup=r'''
import bpy, math, json, traceback
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view
sc=bpy.context.scene
try:
    arm=bpy.data.objects['cmu_sprint']; cam=bpy.data.objects['op_sidecam']; sc.camera=cam
    sc.frame_set(140); bpy.context.view_layer.update()
    mw=arm.matrix_world
    sc.render.resolution_x=1280; sc.render.resolution_y=720
    cam.data.lens=50; cam.data.sensor_fit='VERTICAL'; cam.data.sensor_height=24.0
    KPB={0:'Head',1:'Neck',2:'RightArm',3:'RightForeArm',4:'RightHand',5:'LeftArm',6:'LeftForeArm',
         7:'LeftHand',8:'RightUpLeg',9:'RightLeg',10:'RightFoot',11:'LeftUpLeg',12:'LeftLeg',13:'LeftFoot'}
    # ---- anatomical face KP from real Head bone (camera-independent world positions) ----
    def face_world():
        pos={}
        for i,bn in KPB.items():
            pb=arm.pose.bones.get(bn)
            if pb: pos[i]=mw@pb.head
        hb=arm.pose.bones['Head']; M=(mw.to_3x3()@hb.matrix.to_3x3())
        up_h=M.col[1].normalized(); fwd_h=(-M.col[2]).normalized(); right_h=fwd_h.cross(up_h).normalized()
        # face-KP offsets = RATIOS of actual head-bone length (hl); scale with figure, no magic absolutes
        hl=(mw@hb.tail - mw@hb.head).length
        c=(mw@hb.head + mw@hb.tail)*0.5                      # skull center
        pos[0] =c + fwd_h*0.45*hl - up_h*0.05*hl             # Nose: modest forward (~half head depth)
        pos[14]=c + fwd_h*0.22*hl + up_h*0.18*hl + right_h*0.16*hl   # REye
        pos[15]=c + fwd_h*0.22*hl + up_h*0.18*hl - right_h*0.16*hl   # LEye
        pos[16]=c - fwd_h*0.30*hl + up_h*0.08*hl + right_h*0.42*hl   # REar
        pos[17]=c - fwd_h*0.30*hl + up_h*0.08*hl - right_h*0.42*hl   # LEar
        return pos
    POS=face_world()
    def frame_project(target_bones, fill):
        if target_bones is None:
            tp=[]
            for pb in arm.pose.bones: tp+=[mw@pb.head, mw@pb.tail]
        else:
            tp=[]
            for nm in target_bones:
                pb=arm.pose.bones.get(nm)
                if pb: tp+=[mw@pb.head, mw@pb.tail]
        xs=[p.x for p in tp]; ys=[p.y for p in tp]; zs=[p.z for p in tp]
        bc=Vector(((min(xs)+max(xs))/2,(min(ys)+max(ys))/2,(min(zs)+max(zs))/2))
        ey=max(ys)-min(ys); ez=max(zs)-min(zs)
        tv=math.tan(math.atan(12.0/50.0)); th=tv*(1280/720)
        d=max((ez/2)/tv,(ey/2)/th)/fill
        cam.location=bc+Vector((-d,0,0))    # -X side = facing RIGHT
        cam.rotation_euler=(bc-cam.location).to_track_quat('-Z','Y').to_euler()
        bpy.context.view_layer.update()
        cam_e=cam.evaluated_get(bpy.context.evaluated_depsgraph_get())
        p18=[None]*18
        for i,p in POS.items():
            uv=world_to_camera_view(sc,cam_e,p); p18[i]=[round(uv.x,4),round(uv.y,4)]
        return p18
    BUST=['Head','Neck','Neck1','Spine','Spine1','LowerBack','LeftShoulder','RightShoulder',
          'LeftArm','RightArm','LeftForeArm','RightForeArm','LeftHand','RightHand']
    full=frame_project(None, 0.88)
    bust=frame_project(BUST, 0.82)
    json.dump({'p18':full},open(r"C:\Users\bokan.DC1\AppData\Local\Temp\op18_full.json","w"))
    json.dump({'p18':bust},open(r"C:\Users\bokan.DC1\AppData\Local\Temp\op18_bust.json","w"))
    print("full nose=%s neck=%s | bust nose=%s neck=%s"%(full[0],full[1],bust[0],bust[1]))
except Exception:
    print("PYERR", traceback.format_exc())
'''
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
print(call({"type":"execute_code","params":{"code":setup}}))
