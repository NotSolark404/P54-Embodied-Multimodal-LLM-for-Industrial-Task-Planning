import socket
import time

ROBOT_IP = "172.21.0.121"

# blocking=True — waits until gripper finishes moving
script = "rg_grip(580, 40, 0, False, False)\n"

for port in [30001, 30002]:
    print(f"\n--- Trying port {port} ---")
    try:
        with socket.create_connection((ROBOT_IP, port), timeout=5) as s:
            s.sendall(script.encode("utf-8"))
            print(f"Sent to port {port}: {script.strip()}")
            time.sleep(4)
            try:
                s.settimeout(1)
                resp = s.recv(4096)
                print(f"Response ({len(resp)} bytes): {resp[:80]!r}")
            except socket.timeout:
                print("No response (normal).")
    except Exception as e:
        print(f"Error: {e}")