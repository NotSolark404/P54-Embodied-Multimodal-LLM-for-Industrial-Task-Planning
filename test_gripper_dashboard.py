import socket
import time

ROBOT_IP  = "172.21.0.121"
DASH_PORT = 29999

def dashboard(cmd):
    print(f">> {cmd}")
    s.sendall((cmd + "\n").encode())
    time.sleep(0.3)
    resp = s.recv(4096).decode("utf-8", errors="replace").strip()
    print(f"<< {resp}")
    return resp

with socket.create_connection((ROBOT_IP, DASH_PORT), timeout=5) as s:
    s.settimeout(5)
    banner = s.recv(4096).decode()
    print("Connected:", banner.strip())

    dashboard("load grip_open.urp")
    time.sleep(1)
    dashboard("play")
    time.sleep(5)
    dashboard("stop")

    time.sleep(1)

    dashboard("load grip_close.urp")
    time.sleep(1)
    dashboard("play")
    time.sleep(5)
    dashboard("stop")