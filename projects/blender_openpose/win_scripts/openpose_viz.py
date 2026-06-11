setup=r'''
import bpy, math
from mathutils import Vector
import traceback
sc=bpy.context.scene
try:
    arm=bpy.data.objects['cmu_sprint']; cam=bpy.data.objects['op_sidecam']; sc.camera=cam
    arm.hide_viewport=False; arm.hide_set(False)
    sc.frame_set(140); bpy.context.view_layer.update()
    KPB={0:'Head',1:'Neck',2:'RightArm',3:'RightForeArm',4:'RightHand',5:'LeftArm',6:'LeftForeArm',
         7:'LeftHand',8:'RightUpLeg',9:'RightLeg',10:'RightFoot',11:'LeftUpLeg',12:'LeftLeg',13:'LeftFoot'}
    COL=[(1,0,0),(1,.33,0),(1,.66,0),(1,1,0),(.66,1,0),(.33,1,0),(0,1,0),(0,1,.33),(0,1,.66),
         (0,1,1),(0,.66,1),(0,.33,1),(0,0,1),(.33,0,1),(.66,0,1),(1,0,1),(1,0,.66),(1,0,.33)]
    LIMBS=[(1,2),(1,5),(2,3),(3,4),(5,6),(6,7),(1,8),(8,9),(9,10),(1,11),(11,12),(12,13),(1,0),
           (0,14),(0,15),(14,16),(15,17)]
    pos={}
    for i,bn in KPB.items():
        pb=arm.pose.bones.get(bn)
        if pb: pos[i]=arm.matrix_world@pb.head
    head=pos[0]; neck=pos[1]; hs=max((head-neck).length,1e-4)
    R=(cam.matrix_world.to_3x3()@Vector((1,0,0))).normalized()  # camera screen-right in world
    U=(cam.matrix_world.to_3x3()@Vector((0,1,0))).normalized()  # camera screen-up in world
    s=-1.0   # facing RIGHT in screen
    pos[0] =head + R*(s*0.45*hs) - U*(0.18*hs)   # Nose
    pos[14]=head + R*(s*0.26*hs) - U*(0.05*hs)
    pos[15]=head + R*(s*0.30*hs) + U*(0.04*hs)
    pos[16]=head - R*(s*0.18*hs) + U*(0.02*hs)
    pos[17]=head - R*(s*0.16*hs) + U*(0.11*hs)
    zs=[p.z for p in pos.values()]; H3=max(zs)-min(zs)
    jr=H3*0.020; lr=H3*0.013
    # materials (emission)
    def emat(name,rgb):
        m=bpy.data.materials.get(name) or bpy.data.materials.new(name)
        m.use_nodes=True; nt=m.node_tree; nt.nodes.clear()
        e=nt.nodes.new('ShaderNodeEmission'); e.inputs[0].default_value=(rgb[0],rgb[1],rgb[2],1.0); e.inputs[1].default_value=1.2
        o=nt.nodes.new('ShaderNodeOutputMaterial'); nt.links.new(e.outputs[0],o.inputs[0])
        m.diffuse_color=(rgb[0],rgb[1],rgb[2],1.0)
        return m
    # collection (clear/create)
    coll=bpy.data.collections.get('OpenPoseViz')
    if coll:
        for o in list(coll.objects): bpy.data.objects.remove(o,do_unlink=True)
    else:
        coll=bpy.data.collections.new('OpenPoseViz'); sc.collection.children.link(coll)
    def to_coll(ob):
        for c in list(ob.users_collection): c.objects.unlink(ob)
        coll.objects.link(ob)
    # joints
    for i,p in pos.items():
        bpy.ops.mesh.primitive_uv_sphere_add(segments=14,ring_count=8,radius=jr,location=p)
        ob=bpy.context.active_object; ob.name="op_j%02d"%i
        bpy.ops.object.shade_smooth()
        ob.data.materials.append(emat("opc_%02d"%i,COL[i])); ob.color=(COL[i][0],COL[i][1],COL[i][2],1.0)
        to_coll(ob)
    # limbs
    for li,(a,b) in enumerate(LIMBS):
        if a not in pos or b not in pos: continue
        pa,pb_=pos[a],pos[b]; d=pb_-pa; L=d.length
        if L<1e-5: continue
        bpy.ops.mesh.primitive_cylinder_add(vertices=12,radius=lr,depth=L,location=(pa+pb_)/2)
        ob=bpy.context.active_object; ob.name="op_l%02d"%li
        q=Vector((0,0,1)).rotation_difference(d.normalized()); ob.rotation_euler=q.to_euler()
        ob.data.materials.append(emat("opl_%02d"%li,COL[li])); ob.color=(COL[li][0],COL[li][1],COL[li][2],1.0)
        to_coll(ob)
    arm.hide_viewport=True   # hide gray armature, show OpenPose viz instead
    print("OpenPoseViz built joints=%d limbs=%d H3=%.2f jr=%.3f"%(len(pos),len(LIMBS),H3,jr))
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
