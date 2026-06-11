import socket, json
s=socket.socket(socket.AF_INET,socket.SOCK_STREAM); s.settimeout(20)
try:
    s.connect(("127.0.0.1",9876))
    s.sendall(json.dumps({"type":"get_scene_info"}).encode())
    buf=bytearray()
    while True:
        c=s.recv(8192)
        if not c: break
        buf.extend(c)
        try:
            d=json.loads(bytes(buf).decode("utf-8").split("\0")[0]); print(json.dumps(d)[:600]); break
        except: continue
except Exception as e:
    print("DEAD", type(e).__name__, e)
finally:
    s.close()
