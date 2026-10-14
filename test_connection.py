# scripts/test_connection.py
import socket

ROBOT_IP = "172.21.0.121"

script = """
def go_home():
  movej([-1.568847, -2.343778, 2.104474, -1.361051, -1.565358, -4.708451], a=0.05, v=0.05)
end
go_home()
"""

with socket.create_connection((ROBOT_IP, 30002), timeout=5) as s:
    s.sendall((script + "\n").encode("utf-8"))
    print("Returning to home position...")