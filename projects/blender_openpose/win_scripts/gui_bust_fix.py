setup=r'''
import bpy, mathutils, math, traceback
sc=bpy.context.scene
try:
    arm=bpy.data.objects['cmu_sprint']
    # --- make sure the armature is actually visible in the viewport ---
    arm.hide_viewport=False; arm.hide_set(False); arm.hide_render=False
    arm.show_in_front=True
    try: arm.data.display_type='OCTAHEDRAL'
    except: pass
    # unhide/enable its collections in the view layer
    def show_colls(coll):
        lc=None
        def find(layer):
            if layer.collection==coll: return layer
            for ch in layer.children:
                r=find(ch)
                if r: return r
        vl=bpy.context.view_layer
        for c in arm.users_collection:
            lcc=find(vl.layer_collection)
            if lcc: lcc.exclude=False; lcc.hide_viewport=False
        c=arm.users_collection
    for c in arm.users_collection:
        c.hide_viewport=False
    # select + active
    bpy.ops.object.select_all(action='DESELECT')
    arm.select_set(True); bpy.context.view_layer.objects.active=arm
    sc.frame_set(140); bpy.context.view_layer.update()
    # area / shading
    win=bpy.context.window
    area=max([a for a in win.screen.areas if a.type=='VIEW_3D'], key=lambda a:a.width*a.height)
    region=next(r for r in area.regions if r.type=='WINDOW'); sp=area.spaces.active
    sp.overlay.show_overlays=True
    sp.shading.type='SOLID'
    rv=sp.region_3d
    with bpy.context.temp_override(window=win,area=area,region=region):
        bpy.ops.view3d.view_camera()
        bpy.ops.view3d.view_center_camera()
        bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=4)
    print("visible=%s hide_get=%s in_front=%s colls=%s"%(
        not arm.hide_viewport, arm.hide_get(), arm.show_in_front,[c.name for c in arm.users_collection]))
except Exception:
    print("PYERR", traceback.format_exc())
'''
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
print(call({"type":"execute_code","params":{"code":setup}}))
print(call({"type":"get_viewport_screenshot","params":{"max_size":1280,"filepath":r"C:\Users\bokan.DC1\AppData\Local\Temp\gui_bust_fix.png","format":"png"}})[:80])
