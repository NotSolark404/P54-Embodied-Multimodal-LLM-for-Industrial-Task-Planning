# """
# ur5_script_robot.py
# -------------------
# Controls UR5 by sending URScript commands over TCP (port 30002).
# Gripper: OnRobot RG2 via Dashboard Server (port 29999) loading saved .urp programs.

# IMPORTANT: every new script sent to 30002 (and every dashboard 'load') replaces
# whatever is currently running. So we must WAIT for each move to finish before
# sending the next command, otherwise moves get cut off partway.

# Setup required on teach pendant:
#     - Save 'grip_close.urp': RG2 node, width=60mm, force=40N
#     - Save 'grip_open.urp':  RG2 node, width=67mm, force=40N
#     (these programs must contain ONLY the RG2 node - no waypoints)

# Set in .env:
#     ROBOT_BACKEND=urscript
#     UR5_ROBOT_IP=172.21.0.121
#     UR5_MOVE_SPEED=0.05
#     UR5_MOVE_ACCEL=0.05
# """

# import math
# import os
# import socket
# import time
# import logging
# from typing import Optional

# logger = logging.getLogger(__name__)

# # ── Config ─────────────────────────────────────────────────────────────────────
# UR5_IP       = os.getenv("UR5_ROBOT_IP",    "172.21.0.121")
# UR5_PORT     = 30002
# DASH_PORT    = 29999
# MOVE_SPEED   = float(os.getenv("UR5_MOVE_SPEED",  "0.05"))   # m/s
# MOVE_ACCEL   = float(os.getenv("UR5_MOVE_ACCEL",  "0.05"))   # m/s^2
# APPROACH_H   = 0.10   # metres above target z before descending
# TRANSIT_Z    = 0.35   # safe height for ALL lateral moves
# BLEND        = 0.0    # no blending - a blended final move can stop short
# GRIPPER_WAIT = 4.0
# WAIT_MARGIN  = 1.0    # extra seconds added to every move wait
# UNKNOWN_DIST = 0.8    # assumed distance (m) when we don't know where the arm is

# HOME_SPEED   = 0.3    # rad/s for movej home
# HOME_ACCEL   = 0.3    # rad/s^2
# HOME_WAIT    = 15.0   # seconds to wait for homing

# GRIP_Z   = -0.016442  # same height used for both pick and place (recorded at grey tray pick)
# PICK_Z   = GRIP_Z
# PLACE_Z  = GRIP_Z

# HOME_JOINTS = [-1.568847, -2.343778, 2.104474, -1.361051, -1.565358, -4.708451]

# POSITIONS = {
#     "bottom tray slot 1": [-0.433125, -0.004389,  0.002967,  3.138130, -0.045465,  0.000987],
#     "bottom tray slot 2": [-0.438373, -0.112308,  0.002967,  3.138118, -0.045475,  0.001013],
#     "bottom tray slot 3": [-0.296695, -0.001337,  0.002967,  3.138090, -0.045475,  0.000978],
#     "top tray slot 1":    [-0.432884,  0.162100,  0.032872, -3.132174,  0.029799,  0.015700],
#     "top tray slot 2":    [-0.429305,  0.274608,  0.002967, -3.132172,  0.029563,  0.015840],
#     "top tray slot 3":    [-0.287118,  0.270020,  0.002967, -3.132196,  0.029646,  0.015836],
#     "grey tray":          [-0.433482, -0.004889, -0.016442, -3.132216,  0.029897,  0.015678],
# }


# def move_duration(dist: float, v: float, a: float) -> float:
#     """Time for a trapezoidal velocity profile covering `dist` metres."""
#     if dist <= 0:
#         return 0.0
#     if dist >= v * v / a:
#         # accelerate, cruise at v, decelerate
#         return dist / v + v / a
#     # too short to reach full speed - triangular profile
#     return 2.0 * math.sqrt(dist / a)


# class UR5ScriptRobot:
#     def __init__(self):
#         self._ip       = UR5_IP
#         self._held: Optional[str] = None
#         self._current_pose: Optional[list] = None   # target (slot) pose we're working at
#         self._last_cmd: Optional[list] = None       # last pose actually commanded to the arm
#         self._scene: dict = {}
#         self._connected = self._check_connection()
#         status = f"Connected to {self._ip}" if self._connected else "UNREACHABLE — dry-run mode"
#         print(f"\n  [UR5] {status}")
#         # print live config so you can confirm which version of this file is running
#         print(f"  [UR5] PICK_Z={PICK_Z}  PLACE_Z={PLACE_Z}  speed={MOVE_SPEED}  accel={MOVE_ACCEL}\n")
#         logger.info(f"[UR5] {status}")

#     def _check_connection(self) -> bool:
#         try:
#             with socket.create_connection((self._ip, UR5_PORT), timeout=2.0):
#                 return True
#         except OSError:
#             return False

#     def _send_script(self, script: str) -> bool:
#         if not self._connected:
#             logger.info(f"[UR5][DRY-RUN] {script.strip()[:80]}")
#             return False
#         try:
#             with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
#                 s.settimeout(15.0)
#                 s.connect((self._ip, UR5_PORT))
#                 s.sendall((script.strip() + "\n").encode("utf-8"))
#             logger.info(f"[UR5] SENT: {script.strip()[:80]}")
#             return True
#         except Exception as e:
#             logger.warning(f"[UR5] Send failed: {e}")
#             return False

#     def _dashboard(self, cmd: str) -> str:
#         if not self._connected:
#             logger.info(f"[UR5][DRY-RUN] dashboard: {cmd}")
#             return "dry-run"
#         try:
#             with socket.create_connection((self._ip, DASH_PORT), timeout=5.0) as s:
#                 s.settimeout(5.0)
#                 s.recv(4096)
#                 s.sendall((cmd + "\n").encode())
#                 time.sleep(0.3)
#                 resp = s.recv(4096).decode("utf-8", errors="replace").strip()
#             logger.info(f"[UR5] DASH {cmd!r} → {resp}")
#             return resp
#         except Exception as e:
#             logger.warning(f"[UR5] Dashboard failed: {e}")
#             return ""

#     def load_scene(self, scene: dict) -> None:
#         self._scene = {}
#         for obj in scene.get("objects", []):
#             label = obj.get("label") or obj.get("name", "")
#             pos   = obj.get("position", (0.0, 0.0))
#             if isinstance(pos, (list, tuple)):
#                 self._scene[label] = (float(pos[0]), float(pos[1]))
#         logger.info(f"[UR5] Scene loaded: {list(self._scene.keys())}")

#     def locate(self, object_name: str):
#         from simulation_backend.mock_robot import CommandResult
#         name_lower = object_name.lower()
#         for label in self._scene:
#             if name_lower in label.lower():
#                 print(f"  [UR5] LOCATE  '{label}'")
#                 return CommandResult(success=True, command="locate", message=f"Found '{label}'")
#         return CommandResult(success=False, command="locate", message=f"'{object_name}' not in scene")

#     def move_to_object(self, object_name: str):
#         from simulation_backend.mock_robot import CommandResult
#         pose = self._resolve_pose(object_name)
#         if pose is None:
#             return CommandResult(success=False, command="move", message=f"No pose for '{object_name}'")
#         x, y, z, rx, ry, rz = pose

#         # lift straight up first if we're below transit height
#         if self._last_cmd is not None:
#             cx, cy, cz, crx, cry, crz = self._last_cmd
#             if cz < TRANSIT_Z - 0.005:
#                 self._move_to_pose(cx, cy, TRANSIT_Z, crx, cry, crz, label="LIFT")

#         self._move_to_pose(x, y, TRANSIT_Z, rx, ry, rz, label="TRANSIT")
#         self._move_to_pose(x, y, z + APPROACH_H, rx, ry, rz, label="APPROACH")

#         self._current_pose = pose
#         return CommandResult(success=True, command="move", message=f"At approach for '{object_name}'")

#     def pick(self, object_name: str):
#         """Picks at the current location if move_to_object() was called first,
#         otherwise moves to object_name's pose and picks there."""
#         from simulation_backend.mock_robot import CommandResult
#         if self._held:
#             return CommandResult(success=False, command="pick", message=f"Already holding '{self._held}'")
#         if self._current_pose is None:
#             res = self.move_to_object(object_name)
#             if not res.success:
#                 return res

#         x, y, z, rx, ry, rz = self._current_pose
#         print(f"  [UR5] PICK    '{object_name}' at ({x:.3f}, {y:.3f})")
#         self._gripper_open()
#         self._move_to_pose(x, y, PICK_Z, rx, ry, rz, label="DESCEND", speed_factor=0.5)
#         self._gripper_close()
#         self._move_to_pose(x, y, PICK_Z + APPROACH_H, rx, ry, rz, label="ASCEND", speed_factor=0.5)

#         self._held = object_name
#         return CommandResult(success=True, command="pick", message=f"Picked '{object_name}'")

#     def place(self, object_name: str):
#         from simulation_backend.mock_robot import CommandResult
#         res = self.move_to_object(object_name)
#         if not res.success:
#             return res

#         x, y, z, rx, ry, rz = self._current_pose
#         print(f"  [UR5] PLACE   '{self._held}' → '{object_name}'")
#         self._move_to_pose(x, y, PLACE_Z, rx, ry, rz, label="DESCEND", speed_factor=0.5)
#         self._gripper_open()
#         self._move_to_pose(x, y, PLACE_Z + APPROACH_H, rx, ry, rz, label="ASCEND", speed_factor=0.5)

#         self._held = None
#         return CommandResult(success=True, command="place", message=f"Placed at '{object_name}'")

#     def reset(self) -> None:
#         j = HOME_JOINTS
#         script = (f"movej([{j[0]},{j[1]},{j[2]},{j[3]},{j[4]},{j[5]}], a={HOME_ACCEL}, v={HOME_SPEED})")
#         print("  [UR5] HOME")
#         self._send_script(script)
#         if self._connected:
#             time.sleep(HOME_WAIT)
#         self._held = None
#         self._current_pose = None
#         self._last_cmd = None   # we don't track the home pose in cartesian space

#     def stop(self) -> None:
#         self._send_script("stopj(2.0)")
#         logger.warning("[UR5] Emergency stop sent")

#     def get_state(self) -> dict:
#         return {"ip": self._ip, "connected": self._connected, "held_object": self._held,
#                 "pose": self._current_pose, "last_cmd": self._last_cmd}

#     def _resolve_pose(self, object_name: str) -> Optional[list]:
#         name = object_name.lower().strip()

#         # 1. exact match
#         for key, pose in POSITIONS.items():
#             if key.lower() == name:
#                 return pose

#         # 2. substring match, but only if it's unambiguous
#         matches = [key for key in POSITIONS if name in key.lower()]
#         if len(matches) == 1:
#             return POSITIONS[matches[0]]
#         if len(matches) > 1:
#             logger.warning(f"[UR5] '{object_name}' is ambiguous: {matches}")
#         return None

#     def _move_to_pose(self, x, y, z, rx, ry, rz, label="MOVE", speed_factor=1.0) -> None:
#         v = MOVE_SPEED * speed_factor
#         a = MOVE_ACCEL * speed_factor
#         script = (f"movel(p[{x:.6f},{y:.6f},{z:.6f},{rx:.6f},{ry:.6f},{rz:.6f}], "
#                   f"a={a:.4f}, v={v:.4f}, r={BLEND})")

#         # work out how far we're going so we can wait long enough
#         if self._last_cmd is not None:
#             lx, ly, lz = self._last_cmd[:3]
#             dist = math.sqrt((x - lx) ** 2 + (y - ly) ** 2 + (z - lz) ** 2)
#         else:
#             dist = UNKNOWN_DIST
#         wait = move_duration(dist, v, a) * 1.2 + WAIT_MARGIN

#         print(f"  [UR5] {label:<10} ({x:.3f}, {y:.3f}, {z:.3f})  dist={dist:.3f}m  wait={wait:.1f}s")
#         self._send_script(script)
#         if self._connected:
#             time.sleep(wait)
#         self._last_cmd = [x, y, z, rx, ry, rz]

#     def _gripper_close(self) -> None:
#         print("  [UR5] GRIP CLOSE")
#         self._run_gripper_program("grip_close.urp")

#     def _gripper_open(self) -> None:
#         print("  [UR5] GRIP OPEN")
#         self._run_gripper_program("grip_open.urp")

#     def _run_gripper_program(self, program: str) -> None:
#         self._dashboard(f"load {program}")
#         time.sleep(0.5)
#         self._dashboard("play")
#         time.sleep(GRIPPER_WAIT if self._connected else 0.05)
#         self._dashboard("stop")


"""
ur5_script_robot.py
-------------------
Controls UR5 by sending URScript commands over TCP (port 30002).
Gripper: OnRobot RG2 via Dashboard Server (port 29999) loading saved .urp programs.

IMPORTANT: every new script sent to 30002 (and every dashboard 'load') replaces
whatever is currently running. So we must WAIT for each move to finish before
sending the next command, otherwise moves get cut off partway.

Setup required on teach pendant:
    - Save 'grip_close.urp': RG2 node, width=60mm, force=40N
    - Save 'grip_open.urp':  RG2 node, width=67mm, force=40N
    (these programs must contain ONLY the RG2 node - no waypoints)

Set in .env:
    ROBOT_BACKEND=urscript
    UR5_ROBOT_IP=172.21.0.121
    UR5_MOVE_SPEED=0.05
    UR5_MOVE_ACCEL=0.05
"""

import math
import os
import socket
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────
UR5_IP       = os.getenv("UR5_ROBOT_IP",    "172.21.0.121")
UR5_PORT     = 30002
DASH_PORT    = 29999
MOVE_SPEED   = float(os.getenv("UR5_MOVE_SPEED",  "0.05"))   # m/s
MOVE_ACCEL   = float(os.getenv("UR5_MOVE_ACCEL",  "0.05"))   # m/s^2
APPROACH_H   = 0.10   # metres above target z before descending
TRANSIT_Z    = 0.35   # safe height for ALL lateral moves
BLEND        = 0.0    # no blending - a blended final move can stop short
GRIPPER_WAIT = 4.0
WAIT_MARGIN  = 1.0    # extra seconds added to every move wait
UNKNOWN_DIST = 0.8    # assumed distance (m) when we don't know where the arm is

HOME_SPEED   = 0.3    # rad/s for movej home
HOME_ACCEL   = 0.3    # rad/s^2
HOME_WAIT    = 15.0   # seconds to wait for homing

GRIP_Z   = -0.016442  # same height used for both pick and place (recorded at grey tray pick)
PICK_Z   = GRIP_Z
PLACE_Z  = GRIP_Z

HOME_JOINTS = [-1.568847, -2.343778, 2.104474, -1.361051, -1.565358, -4.708451]

POSITIONS = {
    "bottom tray slot 1": [-0.433125, -0.004389,  0.002967,  3.138130, -0.045465,  0.000987],
    "bottom tray slot 2": [-0.438373, -0.112308,  0.002967,  3.138118, -0.045475,  0.001013],
    "bottom tray slot 3": [-0.296695, -0.001337,  0.002967,  3.138090, -0.045475,  0.000978],
    "top tray slot 1":    [-0.432884,  0.162100,  0.032872, -3.132174,  0.029799,  0.015700],
    "top tray slot 2":    [-0.429305,  0.274608,  0.002967, -3.132172,  0.029563,  0.015840],
    "top tray slot 3":    [-0.287118,  0.270020,  0.002967, -3.132196,  0.029646,  0.015836],
    "grey tray":          [-0.433482, -0.004889, -0.016442, -3.132216,  0.029897,  0.015678],
}


def build_scene() -> dict:
    """Scene made from the recorded POSITIONS, so the planner sees real names."""
    objects = []
    for name, pose in POSITIONS.items():
        objects.append({"label": name, "position": (pose[0], pose[1])})
    return {"objects": objects}

def move_duration(dist: float, v: float, a: float) -> float:
    """Time for a trapezoidal velocity profile covering `dist` metres."""
    if dist <= 0:
        return 0.0
    if dist >= v * v / a:
        # accelerate, cruise at v, decelerate
        return dist / v + v / a
    # too short to reach full speed - triangular profile
    return 2.0 * math.sqrt(dist / a)


class UR5ScriptRobot:
    def __init__(self):
        self._ip       = UR5_IP
        self._held: Optional[str] = None
        self._current_pose: Optional[list] = None   # target (slot) pose we're working at
        self._last_cmd: Optional[list] = None       # last pose actually commanded to the arm
        self._scene: dict = {}
        self._connected = self._check_connection()
        status = f"Connected to {self._ip}" if self._connected else "UNREACHABLE — dry-run mode"
        print(f"\n  [UR5] {status}")
        # print live config so you can confirm which version of this file is running
        print(f"  [UR5] PICK_Z={PICK_Z}  PLACE_Z={PLACE_Z}  speed={MOVE_SPEED}  accel={MOVE_ACCEL}\n")
        logger.info(f"[UR5] {status}")

    def _check_connection(self) -> bool:
        try:
            with socket.create_connection((self._ip, UR5_PORT), timeout=2.0):
                return True
        except OSError:
            return False

    def _send_script(self, script: str) -> bool:
        if not self._connected:
            logger.info(f"[UR5][DRY-RUN] {script.strip()[:80]}")
            return False
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(15.0)
                s.connect((self._ip, UR5_PORT))
                s.sendall((script.strip() + "\n").encode("utf-8"))
            logger.info(f"[UR5] SENT: {script.strip()[:80]}")
            return True
        except Exception as e:
            logger.warning(f"[UR5] Send failed: {e}")
            return False

    def _dashboard(self, cmd: str) -> str:
        if not self._connected:
            logger.info(f"[UR5][DRY-RUN] dashboard: {cmd}")
            return "dry-run"
        try:
            with socket.create_connection((self._ip, DASH_PORT), timeout=5.0) as s:
                s.settimeout(5.0)
                s.recv(4096)
                s.sendall((cmd + "\n").encode())
                time.sleep(0.3)
                resp = s.recv(4096).decode("utf-8", errors="replace").strip()
            logger.info(f"[UR5] DASH {cmd!r} → {resp}")
            return resp
        except Exception as e:
            logger.warning(f"[UR5] Dashboard failed: {e}")
            return ""

    def load_scene(self, scene: dict) -> None:
        self._scene = {}
        for obj in scene.get("objects", []):
            label = obj.get("label") or obj.get("name", "")
            pos   = obj.get("position", (0.0, 0.0))
            if isinstance(pos, (list, tuple)):
                self._scene[label] = (float(pos[0]), float(pos[1]))
        logger.info(f"[UR5] Scene loaded: {list(self._scene.keys())}")

    def locate(self, object_name: str):
        from simulation_backend.mock_robot import CommandResult
        name_lower = object_name.lower()
        for label in self._scene:
            if name_lower in label.lower():
                print(f"  [UR5] LOCATE  '{label}'")
                return CommandResult(success=True, command="locate", message=f"Found '{label}'")
        return CommandResult(success=False, command="locate", message=f"'{object_name}' not in scene")

    def move_to_object(self, object_name: str):
        from simulation_backend.mock_robot import CommandResult
        pose = self._resolve_pose(object_name)
        if pose is None:
            return CommandResult(success=False, command="move", message=f"No pose for '{object_name}'")
        x, y, z, rx, ry, rz = pose

        # lift straight up first if we're below transit height
        if self._last_cmd is not None:
            cx, cy, cz, crx, cry, crz = self._last_cmd
            if cz < TRANSIT_Z - 0.005:
                self._move_to_pose(cx, cy, TRANSIT_Z, crx, cry, crz, label="LIFT")

        self._move_to_pose(x, y, TRANSIT_Z, rx, ry, rz, label="TRANSIT")
        self._move_to_pose(x, y, z + APPROACH_H, rx, ry, rz, label="APPROACH")

        self._current_pose = pose
        return CommandResult(success=True, command="move", message=f"At approach for '{object_name}'")

    def pick(self, object_name: str):
        """Moves to object_name's recorded pose and picks there."""
        from simulation_backend.mock_robot import CommandResult
        if self._held:
            return CommandResult(success=False, command="pick", message=f"Already holding '{self._held}'")
        res = self.move_to_object(object_name)
        if not res.success:
            return res

        x, y, z, rx, ry, rz = self._current_pose
        print(f"  [UR5] PICK    '{object_name}' at ({x:.3f}, {y:.3f})")
        self._gripper_open()
        self._move_to_pose(x, y, PICK_Z, rx, ry, rz, label="DESCEND", speed_factor=0.5)
        self._gripper_close()
        self._move_to_pose(x, y, PICK_Z + APPROACH_H, rx, ry, rz, label="ASCEND", speed_factor=0.5)

        self._held = object_name
        return CommandResult(success=True, command="pick", message=f"Picked '{object_name}'")

    def place(self, object_name: str):
        from simulation_backend.mock_robot import CommandResult
        res = self.move_to_object(object_name)
        if not res.success:
            return res

        x, y, z, rx, ry, rz = self._current_pose
        print(f"  [UR5] PLACE   '{self._held}' → '{object_name}'")
        self._move_to_pose(x, y, PLACE_Z, rx, ry, rz, label="DESCEND", speed_factor=0.5)
        self._gripper_open()
        self._move_to_pose(x, y, PLACE_Z + APPROACH_H, rx, ry, rz, label="ASCEND", speed_factor=0.5)

        self._held = None
        return CommandResult(success=True, command="place", message=f"Placed at '{object_name}'")

    def reset(self) -> None:
        j = HOME_JOINTS
        script = (f"movej([{j[0]},{j[1]},{j[2]},{j[3]},{j[4]},{j[5]}], a={HOME_ACCEL}, v={HOME_SPEED})")
        print("  [UR5] HOME")
        self._send_script(script)
        if self._connected:
            time.sleep(HOME_WAIT)
        self._held = None
        self._current_pose = None
        self._last_cmd = None   # we don't track the home pose in cartesian space

    def stop(self) -> None:
        self._send_script("stopj(2.0)")
        logger.warning("[UR5] Emergency stop sent")

    def get_state(self) -> dict:
        return {"ip": self._ip, "connected": self._connected, "held_object": self._held,
                "pose": self._current_pose, "last_cmd": self._last_cmd}

    def _resolve_pose(self, object_name: str) -> Optional[list]:
        name = object_name.lower().strip()

        # 1. exact match
        for key, pose in POSITIONS.items():
            if key.lower() == name:
                return pose

        # 2. substring match, but only if it's unambiguous
        matches = [key for key in POSITIONS if name in key.lower()]
        if len(matches) == 1:
            return POSITIONS[matches[0]]
        if len(matches) > 1:
            logger.warning(f"[UR5] '{object_name}' is ambiguous: {matches}")
        return None

    def _move_to_pose(self, x, y, z, rx, ry, rz, label="MOVE", speed_factor=1.0) -> None:
        v = MOVE_SPEED * speed_factor
        a = MOVE_ACCEL * speed_factor
        script = (f"movel(p[{x:.6f},{y:.6f},{z:.6f},{rx:.6f},{ry:.6f},{rz:.6f}], "
                  f"a={a:.4f}, v={v:.4f}, r={BLEND})")

        # work out how far we're going so we can wait long enough
        if self._last_cmd is not None:
            lx, ly, lz = self._last_cmd[:3]
            dist = math.sqrt((x - lx) ** 2 + (y - ly) ** 2 + (z - lz) ** 2)
        else:
            dist = UNKNOWN_DIST
        wait = move_duration(dist, v, a) * 1.2 + WAIT_MARGIN

        print(f"  [UR5] {label:<10} ({x:.3f}, {y:.3f}, {z:.3f})  dist={dist:.3f}m  wait={wait:.1f}s")
        self._send_script(script)
        if self._connected:
            time.sleep(wait)
        self._last_cmd = [x, y, z, rx, ry, rz]

    def _gripper_close(self) -> None:
        print("  [UR5] GRIP CLOSE")
        self._run_gripper_program("grip_close.urp")

    def _gripper_open(self) -> None:
        print("  [UR5] GRIP OPEN")
        self._run_gripper_program("grip_open.urp")

    def _run_gripper_program(self, program: str) -> None:
        self._dashboard(f"load {program}")
        time.sleep(0.5)
        self._dashboard("play")
        time.sleep(GRIPPER_WAIT if self._connected else 0.05)
        self._dashboard("stop")