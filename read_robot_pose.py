import socket
import time
import struct

ROBOT_IP = "172.21.0.121"

LABEL = input("Enter position name (e.g. 'left tray slot 1'): ").strip()

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.connect((ROBOT_IP, 30003))
time.sleep(0.5)
data = s.recv(1500)
s.close()

pose = struct.unpack_from('!6d', data, 444)
x, y, z, rx, ry, rz = pose

print(f"\n── {LABEL} ──")
print(f"  x={x:.6f}, y={y:.6f}, z={z:.6f}")
print(f"  rx={rx:.6f}, ry={ry:.6f}, rz={rz:.6f}")
vals = ", ".join(f"{v:.6f}" for v in pose)
print(f'\n  "{LABEL}": [{vals}],')