"
import socket, time
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.connect(('172.21.0.121', 30002))
s.sendall(b'movej([0,-1.5708,0,-1.5708,0,0], a=0.1, v=0.05)\n')
time.sleep(3)
s.close()
print('Done')
"

import socket, time, struct

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.connect(('172.21.0.121', 30003))  # real-time port
time.sleep(0.5)
data = s.recv(1500)

# Joint positions are at byte offset 252, 6 doubles
joints = struct.unpack_from('!6d', data, 252)
print("Joint positions (radians):")
for i, j in enumerate(joints):
    print(f"  Joint {i}: {j:.6f}")
s.close()

# Joint positions (radians):
#   Joint 0: -1.568847
#   Joint 1: -2.343778
#   Joint 2: 2.104474
#   Joint 3: -1.361051
#   Joint 4: -1.565358
#   Joint 5: -4.708451

