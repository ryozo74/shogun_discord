"""Generic Blender MCP driver: reads python from a file (argv[1]) or stdin,
sends via official addon protocol (type=execute, null-byte framed), prints JSON result."""
import socket, json, sys

def call(code, timeout=30.0, strict=True):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect(("127.0.0.1", 9876))
    req = {"type": "execute", "code": code, "strict_json": strict}
    s.sendall((json.dumps(req) + "\0").encode("utf-8"))
    buf = bytearray()
    try:
        while b"\0" not in buf:
            c = s.recv(8192)
            if not c:
                break
            buf.extend(c)
    except socket.timeout:
        s.close()
        return {"_error": "timeout", "_buf_len": len(buf)}
    s.close()
    if b"\0" in buf:
        return json.loads(bytes(buf[: buf.index(b"\0")]).decode("utf-8", "replace"))
    return {"_error": "no_delim"}

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else None
    strict = not (len(sys.argv) > 2 and sys.argv[2] == "loose")
    code = open(path, encoding="utf-8").read() if path else sys.stdin.read()
    print(json.dumps(call(code, timeout=30.0, strict=strict), ensure_ascii=False, indent=2))
