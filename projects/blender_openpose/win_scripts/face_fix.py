setup=r'''
import bpy, math, json, traceback
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view
sc=bpy.context.scene
try:
    arm=bpy.data.objects['cmu_sprint']; cam=bpy.data.objects['op_sidecam']; sc.camera=cam
    sc.frame_set(140); bpy.context.view_layer.update()
    mw=arm.matrix_world
    KPB={0:'Head',1:'Neck',2:'RightArm',3:'RightForeArm',4:'RightHand',5:'LeftArm',6:'LeftForeArm',
         7:'LeftHand',8:'RightUpLeg',9:'RightLeg',10:'RightFoot',11:'LeftUpLeg',12:'LeftLeg',13:'LeftFoot'}
    pos={}
    for i,bn in KPB.items():
        pb=arm.pose.bones.get(bn)
        if pb: pos[i]=mw@pb.head
    # --- anatomically-grounded face KP from real Head bone orientation ---
    hb=arm.pose.bones['Head']
    M=(mw.to_3x3()@hb.matrix.to_3x3())
    up_h=M.col[1].normalized()           # along bone = crown up (~+Z)
    fwd_h=(-M.col[2]).normalized()        # -Head_z = anatomical forward (~-Y = FACING)
    right_h=fwd_h.cross(up_h).normalized()# subject's right
    hhead=mw@hb.head; htail=mw@hb.tail
    center=hhead*0.4+htail*0.6
    k=0.11
    pos[0] =center + fwd_h*k                                   # Nose
    pos[14]=center + fwd_h*0.72*k + up_h*0.25*k + right_h*0.32*k  # REye (subject right)
    pos[15]=center + fwd_h*0.72*k + up_h*0.25*k - right_h*0.32*k  # LEye
    pos[16]=center - fwd_h*0.10*k + up_h*0.05*k + right_h*0.80*k  # REar
    pos[17]=center - fwd_h*0.10*k + up_h*0.05*k - right_h*0.80*k  # LEar
    # project
    dg=bpy.context.evaluated_depsgraph_get(); cam_e=cam.evaluated_get(dg)
    p18=[None]*18
    for i,p in pos.items():
        uv=world_to_camera_view(sc,cam_e,p); p18[i]=[round(uv.x,4),round(uv.y,4)]
    json.dump({'p18':p18},open(r"C:\Users\bokan.DC1\AppData\Local\Temp\op18_bust.json","w"))
    # rebuild OpenPoseViz geometry with corrected face KP
    COL=[(1,0,0),(1,.33,0),(1,.66,0),(1,1,0),(.66,1,0),(.33,1,0),(0,1,0),(0,1,.33),(0,1,.66),
         (0,1,1),(0,.66,1),(0,.33,1),(0,0,1),(.33,0,1),(.66,0,1),(1,0,1),(1,0,.66),(1,0,.33)]
    LIMBS=[(1,2),(1,5),(2,3),(3,4),(5,6),(6,7),(1,8),(8,9),(9,10),(1,11),(11,12),(12,13),(1,0),
           (0,14),(0,15),(14,16),(15,17)]
    zs=[p.z for p in pos.values()]; H3=max(zs)-min(zs); jr=H3*0.020; lr=H3*0.013
    def emat(name,rgb):
        m=bpy.data.materials.get(name) or bpy.data.materials.new(name)
        m.use_nodes=True; nt=m.node_tree; nt.nodes.clear()
        e=nt.nodes.new('ShaderNodeEmission'); e.inputs[0].default_value=(rgb[0],rgb[1],rgb[2],1.0); e.inputs[1].default_value=1.2
        o=nt.nodes.new('ShaderNodeOutputMaterial'); nt.links.new(e.outputs[0],o.inputs[0]); m.diffuse_color=(rgb[0],rgb[1],rgb[2],1.0); return m
    coll=bpy.data.collections.get('OpenPoseViz')
    if coll:
        for o in list(coll.objects): bpy.data.objects.remove(o,do_unlink=True)
    else:
        coll=bpy.data.collections.new('OpenPoseViz'); sc.collection.children.link(coll)
    def to_coll(ob):
        for c in list(ob.users_collection): c.objects.unlink(ob)
        coll.objects.link(ob)
    for i,p in pos.items():
        bpy.ops.mesh.primitive_uv_sphere_add(segments=14,ring_count=8,radius=jr,location=p)
        ob=bpy.context.active_object; ob.name="op_j%02d"%i; bpy.ops.object.shade_smooth()
        ob.data.materials.append(emat("opc_%02d"%i,COL[i])); to_coll(ob)
    for li,(a,b) in enumerate(LIMBS):
        if a not in pos or b not in pos: continue
        pa,pb_=pos[a],pos[b]; d=pb_-pa; L=d.length
        if L<1e-5: continue
        bpy.ops.mesh.primitive_cylinder_add(vertices=12,radius=lr,depth=L,location=(pa+pb_)/2)
        ob=bpy.context.active_object; ob.name="op_l%02d"%li
        q=Vector((0,0,1)).rotation_difference(d.normalized()); ob.rotation_euler=q.to_euler()
        ob.data.materials.append(emat("opl_%02d"%li,COL[li])); to_coll(ob)
    arm.hide_viewport=True
    print("face_fix done nose_uv=%s REye=%s LEye=%s REar=%s LEar=%s"%(p18[0],p18[14],p18[15],p18[16],p18[17]))
    print("fwd_h=%s up_h=%s right_h=%s"%([round(v,2) for v in fwd_h],[round(v,2) for v in up_h],[round(v,2) for v in right_h]))
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
