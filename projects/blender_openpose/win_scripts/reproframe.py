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
import bpy, mathutils, math, traceback
from bpy_extras.object_utils import world_to_camera_view
sc=bpy.context.scene
try:
    sc.render.resolution_x=1280; sc.render.resolution_y=720
    arm=bpy.data.objects['cmu_sprint']; sc.frame_set(140); bpy.context.view_layer.update()
    # --- 3D bbox of all bone head+tail ---
    pts=[]
    for pb in arm.pose.bones:
        pts.append(arm.matrix_world@pb.head); pts.append(arm.matrix_world@pb.tail)
    xs=[p.x for p in pts]; ys=[p.y for p in pts]; zs=[p.z for p in pts]
    bcenter=mathutils.Vector(((min(xs)+max(xs))/2,(min(ys)+max(ys))/2,(min(zs)+max(zs))/2))
    ext_y=max(ys)-min(ys); ext_z=max(zs)-min(zs)   # Y=horizontal(travel), Z=vertical(up)
    cam=bpy.data.objects['op_sidecam']; sc.camera=cam
    cam.data.lens=50; cam.data.sensor_fit='VERTICAL'; cam.data.sensor_height=24.0
    tv=math.tan(math.atan(12.0/cam.data.lens)); th=tv*(1280/720)   # half-FOV tangents (from 4-corner geometry)
    FILL=0.85
    # distance so bbox fits to FILL in the binding dimension
    d=max((ext_z/2)/tv, (ext_y/2)/th)/FILL
    # camera looks -X at bcenter, up +Z
    cam.location=bcenter+mathutils.Vector((d,0,0))
    cam.rotation_euler=(bcenter-cam.location).to_track_quat('-Z','Y').to_euler()
    bpy.context.view_layer.update()
    dg=bpy.context.evaluated_depsgraph_get()
    cam_e=cam.evaluated_get(dg)                     # EVALUATED camera (matches render)
    uvC=world_to_camera_view(sc,cam_e,bcenter)
    # project all bbox corners to check fill
    us=[];vs=[]
    for X in (min(xs),max(xs)):
        for Y in (min(ys),max(ys)):
            for Z in (min(zs),max(zs)):
                uv=world_to_camera_view(sc,cam_e,mathutils.Vector((X,Y,Z))); us.append(uv.x); vs.append(uv.y)
    # GUI camera view
    win=bpy.context.window; area=max([a for a in win.screen.areas if a.type=='VIEW_3D'],key=lambda a:a.width*a.height)
    region=next(r for r in area.regions if r.type=='WINDOW'); sp=area.spaces.active; rv=sp.region_3d
    sp.overlay.show_overlays=False
    if rv.view_perspective!='PERSP': rv.view_perspective='PERSP'
    with bpy.context.temp_override(window=win,area=area,region=region):
        bpy.ops.view3d.view_camera(); bpy.ops.view3d.view_center_camera(); bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP',iterations=3)
    print("bbox_center=%s ext(y,z)=(%.2f,%.2f) d=%.2f | EVAL C_uv=(%.3f,%.3f) u[%.2f..%.2f] v[%.2f..%.2f]"%(
        [round(c,2) for c in bcenter],ext_y,ext_z,d,uvC.x,uvC.y,min(us),max(us),min(vs),max(vs)))
except Exception:
    print("PYERR", traceback.format_exc())
'''
print(call({"type":"execute_code","params":{"code":setup}}))
print(call({"type":"get_viewport_screenshot","params":{"max_size":720,"filepath":r"C:\Users\bokan.DC1\AppData\Local\Temp\gui_repro.png","format":"png"}})[:60])
