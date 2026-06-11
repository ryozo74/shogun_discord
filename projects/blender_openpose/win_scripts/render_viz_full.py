setup=r'''
import bpy, gpu, math, traceback
from mathutils import Vector
sc=bpy.context.scene
try:
    arm=bpy.data.objects['cmu_sprint']; cam=bpy.data.objects['op_sidecam']; sc.camera=cam
    sc.frame_set(140); bpy.context.view_layer.update()
    mw=arm.matrix_world
    # SAME full-body framing as gen_p18 (all bones, -X, FILL 0.88)
    tp=[]
    for pb in arm.pose.bones: tp+=[mw@pb.head, mw@pb.tail]
    xs=[p.x for p in tp]; ys=[p.y for p in tp]; zs=[p.z for p in tp]
    bc=Vector(((min(xs)+max(xs))/2,(min(ys)+max(ys))/2,(min(zs)+max(zs))/2))
    ey=max(ys)-min(ys); ez=max(zs)-min(zs)
    cam.data.lens=50; cam.data.sensor_fit='VERTICAL'; cam.data.sensor_height=24.0
    tv=math.tan(math.atan(12.0/50.0)); th=tv*(1280/720); FILL=0.88
    d=max((ez/2)/tv,(ey/2)/th)/FILL
    cam.location=bc+Vector((-d,0,0)); cam.rotation_euler=(bc-cam.location).to_track_quat('-Z','Y').to_euler()
    bpy.context.view_layer.update()
    W,H=1280,720
    win=bpy.context.window
    area=max([a for a in win.screen.areas if a.type=='VIEW_3D'], key=lambda a:a.width*a.height)
    region=next(r for r in area.regions if r.type=='WINDOW'); space=area.spaces.active
    space.shading.type='MATERIAL'; space.overlay.show_overlays=False
    vl=bpy.context.view_layer; dg=bpy.context.evaluated_depsgraph_get()
    vm=cam.matrix_world.inverted(); proj=cam.calc_matrix_camera(dg,x=W,y=H)
    off=gpu.types.GPUOffScreen(W,H)
    with off.bind():
        fb=gpu.state.active_framebuffer_get(); fb.clear(color=(0,0,0,1), depth=1.0)
        off.draw_view3d(sc, vl, space, region, vm, proj, do_color_management=True, draw_background=False)
        buf=fb.read_color(0,0,W,H,4,0,'FLOAT')
    off.free(); buf.dimensions=W*H*4
    img=bpy.data.images.get("opvizfull")
    if img: bpy.data.images.remove(img)
    img=bpy.data.images.new("opvizfull",W,H,alpha=True); img.pixels.foreach_set(buf)
    img.filepath_raw=r"C:\Users\bokan.DC1\AppData\Local\Temp\op_viz_full.png"; img.file_format='PNG'; img.save()
    print("rendered op_viz_full.png d=%.2f"%d)
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
