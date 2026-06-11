"""Blender 5.1+ official MCP server (bl_ext.user_default.mcp) protocol test.

Protocol:
- Request: JSON with type="execute", code=<python>, strict_json=true; null-byte terminated
- Response: JSON null-byte terminated; result dict under "result" key when status=ok
"""
import socket
import json
import sys


def call(code, timeout=15.0):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect(("127.0.0.1", 9876))
    req = {"type": "execute", "code": code, "strict_json": True}
    payload = (json.dumps(req) + "\0").encode("utf-8")
    s.sendall(payload)
    buf = bytearray()
    try:
        while b"\0" not in buf:
            chunk = s.recv(8192)
            if not chunk:
                break
            buf.extend(chunk)
    except socket.timeout:
        s.close()
        return {"_error": "timeout", "_buf_len": len(buf)}
    s.close()
    if b"\0" in buf:
        msg = bytes(buf[: buf.index(b"\0")]).decode("utf-8", errors="replace")
        try:
            return json.loads(msg)
        except json.JSONDecodeError as e:
            return {"_error": "decode", "_raw": msg[:500], "_exc": str(e)}
    return {"_error": "no_delim", "_buf": buf.decode("utf-8", errors="replace")[:500]}


if __name__ == "__main__":
    code = (
        "import bpy\n"
        "result = {\n"
        "    'blender_version': bpy.app.version_string,\n"
        "    'scene': bpy.context.scene.name,\n"
        "    'frame_current': bpy.context.scene.frame_current,\n"
        "    'blend_file': bpy.data.filepath,\n"
        "    'object_count': len(bpy.data.objects),\n"
        "    'objects_first_10': [o.name for o in bpy.data.objects][:10],\n"
        "    'is_dirty': bpy.data.is_dirty,\n"
        "}\n"
    )
    res = call(code, timeout=15.0)
    print(json.dumps(res, ensure_ascii=False, indent=2))
