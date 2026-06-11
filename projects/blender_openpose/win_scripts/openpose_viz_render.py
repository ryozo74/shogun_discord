setup=r'''
import bpy, gpu, math, traceback
sc=bpy.context.scene
try:
    cam=bpy.data.objects['op_sidecam']; sc.camera=cam
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
    img=bpy.data.images.get("opviz")
    if img: bpy.data.images.remove(img)
    img=bpy.data.images.new("opviz",W,H,alpha=True); img.pixels.foreach_set(buf)
    out=r"C:\Users\bokan.DC1\AppData\Local\Temp\openpose_viz.png"
    img.filepath_raw=out; img.file_format='PNG'; img.save()
    print("rendered openpose_viz.png")
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
