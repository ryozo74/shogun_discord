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
    KP={'Nose':'Head','Neck':'Neck','RShoulder':'RightArm','RElbow':'RightForeArm','RWrist':'RightHand',
        'LShoulder':'LeftArm','LElbow':'LeftForeArm','LWrist':'LeftHand','RHip':'RightUpLeg','RKnee':'RightLeg',
        'RAnkle':'RightFoot','LHip':'LeftUpLeg','LKnee':'LeftLeg','LAnkle':'LeftFoot'}
    wp={k:(arm.matrix_world@arm.pose.bones[b].head) for k,b in KP.items() if b in arm.pose.bones}
    Ps=list(wp.values())
    xs=[p.x for p in Ps]; ys=[p.y for p in Ps]; zs=[p.z for p in Ps]
    bc=mathutils.Vector(((min(xs)+max(xs))/2,(min(ys)+max(ys))/2,(min(zs)+max(zs))/2))   # KEYPOINT bbox center
    ey=max(ys)-min(ys); ez=max(zs)-min(zs)
    cam=sc.camera; cam.data.lens=50; cam.data.sensor_fit='VERTICAL'; cam.data.sensor_height=24.0
    tv=math.tan(math.atan(12.0/50.0)); th=tv*(1280/720); FILL=0.85
    d=max((ez/2)/tv,(ey/2)/th)/FILL
    cam.location=bc+mathutils.Vector((-d,0,0))      # FLIP: -X side, looking +X
    cam.rotation_euler=(bc-cam.location).to_track_quat('-Z','Y').to_euler()
    bpy.context.view_layer.update()
    dg=bpy.context.evaluated_depsgraph_get(); cam_e=cam.evaluated_get(dg)
    out={k:[round(uv.x,4),round(uv.y,4)] for k,uv in ((k,world_to_camera_view(sc,cam_e,wp[k])) for k in wp)}
    cuv=world_to_camera_view(sc,cam_e,bc)
    json.dump({'kp':out},open(r"C:\Users\bokan.DC1\AppData\Local\Temp\flipkp.json","w"))
    # GUI
    win=bpy.context.window; area=max([a for a in win.screen.areas if a.type=='VIEW_3D'],key=lambda a:a.width*a.height)
    region=next(r for r in area.regions if r.type=='WINDOW'); sp=area.spaces.active; rv=sp.region_3d
    if rv.view_perspective!='PERSP': rv.view_perspective='PERSP'
    with bpy.context.temp_override(window=win,area=area,region=region):
        bpy.ops.view3d.view_camera(); bpy.ops.view3d.view_center_camera(); bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP',iterations=2)
    print("FLIPPED -X side, KP center_uv=(%.3f,%.3f) Nose_u=%.2f RHip_u=%.2f"%(cuv.x,cuv.y,out['Nose'][0],out['RHip'][0]))
except Exception:
    print("PYERR", traceback.format_exc())
'''
print(call({"type":"execute_code","params":{"code":setup}}))
