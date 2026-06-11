import socket, json
def call(req, timeout=60):
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
import bpy, traceback
sc=bpy.context.scene
try:
    win=bpy.context.window; area=max([a for a in win.screen.areas if a.type=='VIEW_3D'],key=lambda a:a.width*a.height)
    region=next(r for r in area.regions if r.type=='WINDOW'); sp=area.spaces.active; rv=sp.region_3d
    sp.overlay.show_overlays=False
    with bpy.context.temp_override(window=win,area=area,region=region):
        if rv.view_perspective!='PERSP': rv.view_perspective='PERSP'
        bpy.ops.view3d.view_camera()          # operator: enter camera view
        bpy.ops.view3d.view_center_camera()
        bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP',iterations=3)
    print("persp=%s cam=%s"%(rv.view_perspective,sc.camera.name))
except Exception:
    print("PYERR", traceback.format_exc())
'''
print(call({"type":"execute_code","params":{"code":setup}}))
print(call({"type":"get_viewport_screenshot","params":{"max_size":720,"filepath":r"C:\Users\bokan.DC1\AppData\Local\Temp\gui_camop.png","format":"png"}})[:60])
