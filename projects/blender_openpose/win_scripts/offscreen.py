import socket, json
def call(code, timeout=120):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.settimeout(timeout)
    s.connect(("127.0.0.1", 9876)); s.sendall(json.dumps({"type":"execute_code","params":{"code":code}}).encode())
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
code = r'''
import bpy, gpu, traceback
scene=bpy.context.scene
out=r"C:\Users\bokan.DC1\AppData\Local\Temp\mcp_offscreen.png"
try:
    W,H = scene.render.resolution_x, scene.render.resolution_y
    prev_vl = bpy.context.window.view_layer.name
    bpy.context.window.view_layer = scene.view_layers['Openpose_full']
    vl = bpy.context.view_layer
    win=bpy.context.window
    area=next(a for a in win.screen.areas if a.type=='VIEW_3D')
    space=area.spaces.active
    region=next(r for r in area.regions if r.type=='WINDOW')
    sh=space.shading
    prev=(sh.background_type, tuple(sh.background_color), space.overlay.show_overlays)
    sh.background_type='VIEWPORT'; sh.background_color=(0.0,0.0,0.0)
    space.overlay.show_overlays=False
    cam=scene.camera
    dg=bpy.context.evaluated_depsgraph_get()
    view_matrix = cam.matrix_world.inverted()
    proj = cam.calc_matrix_camera(dg, x=W, y=H)
    off=gpu.types.GPUOffScreen(W,H)
    off.draw_view3d(scene, vl, space, region, view_matrix, proj, do_color_management=True)
    with off.bind():
        fb=gpu.state.active_framebuffer_get()
        buf=fb.read_color(0,0,W,H,4,0,'FLOAT')
    off.free()
    buf.dimensions = W*H*4
    img=bpy.data.images.new("ogl_out", W, H, alpha=True)
    img.pixels.foreach_set(buf)
    img.filepath_raw=out; img.file_format='PNG'; img.save()
    # colorfulness over whole image
    px=list(buf)
    R=px[0::4]; G=px[1::4]; B=px[2::4]
    st=range(0,len(R),11)
    cf=sum(abs(R[i]-G[i])+abs(G[i]-B[i]) for i in st)/len(list(st))
    nb=sum(1 for i in st if max(R[i],G[i],B[i])>0.05)/len(list(st))
    print("OFFSCREEN_OK %dx%d COLORFULNESS=%.4f NONBLACK_FRAC=%.3f MAX=%.3f" % (W,H,cf,nb,max(max(R),max(G),max(B))))
    bpy.data.images.remove(img)
    # restore
    sh.background_type, sh.background_color, space.overlay.show_overlays = prev[0], prev[1], prev[2]
    bpy.context.window.view_layer = scene.view_layers[prev_vl]
except Exception:
    print("PYERR", traceback.format_exc())
'''
print(call(code, timeout=120))
