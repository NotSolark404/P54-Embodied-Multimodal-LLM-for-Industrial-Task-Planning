import socket
import time

ROBOT_IP = "172.21.0.121"

script = "rg_grip(580, 40, 0, False, False)\n"

with socket.create_connection((ROBOT_IP, 30002), timeout=5) as s:
    s.sendall(script.encode("utf-8"))
    print("Sent")
    time.sleep(3)