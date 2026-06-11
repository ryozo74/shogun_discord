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
try:
    acts=[a.name for a in bpy.data.actions]
    # pose libraries / asset poses
    poselib=[]
    for a in bpy.data.actions:
        if a.asset_data is not None: poselib.append(a.name)
    # ARP facial: check for expression-related custom props or bones grouped
    arm=bpy.data.objects.get('OpenPoseBone_v3_rig')
    facebones=[b.name for b in arm.pose.bones if any(k in b.name.lower() for k in ('lips','jaw','eyelid','brow','cheek','tongue'))] if arm else []
    print("ACTIONS:", acts)
    print("ASSET_POSES:", poselib)
    print("FACE_CTRL_BONES count:", len(facebones), "sample:", facebones[:10])
except Exception:
    print("PYERR", traceback.format_exc())
'''
print(call({"type":"execute_code","params":{"code":setup}}))
