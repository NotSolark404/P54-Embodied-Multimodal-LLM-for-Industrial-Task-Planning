"""
ur5_script_robot.py
-------------------
Controls UR5 by sending URScript commands over TCP (port 30002).
Gripper: OnRobot RG2 via Dashboard Server (port 29999) loading saved .urp programs.

Setup required on teach pendant:
    - Save 'grip_close.urp': RG2 node, width=60mm, force=40N
    - Save 'grip_open.urp':  RG2 node, width=67mm, force=40N

Set in .env:
    ROBOT_BACKEND=urscript
    UR5_ROBOT_IP=172.21.0.121
    UR5_MOVE_SPEED=0.05
    UR5_MOVE_ACCEL=0.05
"""

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
MOVE_SPEED   = float(os.getenv("UR5_MOVE_SPEED",  "0.05"))
MOVE_ACCEL   = float(os.getenv("UR5_MOVE_ACCEL",  "0.05"))
APPROACH_H   = 0.10   # metres above recorded z before descending
TRANSIT_Z    = 0.35   # safe height for ALL lateral moves — clears the table near top tray
BLEND        = 0.01   # blend radius to prevent C204A3 protective stop
GRIPPER_WAIT = 4.0    # seconds to wait for grip program to finish

HOME_JOINTS = [-1.568847, -2.343778, 2.104474, -1.361051, -1.565358, -4.708451]

# ── Recorded slot positions [x, y, z, rx, ry, rz] ─────────────────────────────
# z is the actual pick height; approach moves to z + APPROACH_H first
POSITIONS = {
    "bottom tray slot 1": [-0.433125, -0.004389,  0.051413,  3.138130, -0.045465,  0.000987],
    "bottom tray slot 2": [-0.438373, -0.112308,  0.177986,  3.138118, -0.045475,  0.001013],
    "bottom tray slot 3": [-0.296695, -0.001337,  0.158373,  3.138090, -0.045475,  0.000978],
    # "top tray slot 1":    [-0.432930,  0.162761,  0.213637, -3.132231,  0.029664,  0.015672],
    "top tray slot 2":    [-0.429305,  0.274608,  0.168093, -3.132172,  0.029563,  0.015840],
    "top tray slot 3":    [-0.287118,  0.270020,  0.146490, -3.132196,  0.029646,  0.015836],
    # "top tray slot 1":    [-0.432875,  0.162729,  0.041531, -3.132210,  0.029705,  0.015570],
    # "top tray slot 1": [-0.432875, 0.162729, 0.041531, -3.132210, 0.029705, 0.015570],
    "top tray slot 1": [-0.432894, 0.162284, 0.007908, -3.132186, 0.029680, 0.015675],
    "grey tray":          [-0.421358, -0.007463, -0.017294, -3.132196,  0.029557,  0.015674],
}


class UR5ScriptRobot:
    """
    UR5 robot driver using URScript over TCP.
    Gripper controlled via Dashboard Server loading saved .urp programs.
    Falls back to dry-run logging if robot is unreachable.
    Interface matches MockRobot — swap with ROBOT_BACKEND=urscript in .env.
    """

    def __init__(self):
        self._ip       = UR5_IP
        self._held: Optional[str] = None
        self._current_pose: Optional[list] = None
        self._scene: dict = {}
        self._connected = self._check_connection()

        status = f"Connected to {self._ip}" if self._connected else f"UNREACHABLE — dry-run mode"
        print(f"\n  [UR5] {status}\n")
        logger.info(f"[UR5] {status}")

    # ── Connection ──────────────────────────────────────────────────────────────

    def _check_connection(self) -> bool:
        try:
            with socket.create_connection((self._ip, UR5_PORT), timeout=2.0):
                return True
        except OSError:
            return False

    def _send_script(self, script: str) -> bool:
        """Send URScript to port 30002."""
        if not self._connected:
            logger.info(f"[UR5][DRY-RUN] {script.strip()[:80]}")
            time.sleep(0.05)
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
        """Send a command to the Dashboard Server (port 29999)."""
        if not self._connected:
            logger.info(f"[UR5][DRY-RUN] dashboard: {cmd}")
            return "dry-run"
        try:
            with socket.create_connection((self._ip, DASH_PORT), timeout=5.0) as s:
                s.settimeout(5.0)
                s.recv(4096)   # consume banner
                s.sendall((cmd + "\n").encode())
                time.sleep(0.3)
                resp = s.recv(4096).decode("utf-8", errors="replace").strip()
            logger.info(f"[UR5] DASH {cmd!r} → {resp}")
            return resp
        except Exception as e:
            logger.warning(f"[UR5] Dashboard failed: {e}")
            return ""

    # ── Scene ───────────────────────────────────────────────────────────────────

    def load_scene(self, scene: dict) -> None:
        """Load current scene from vision module."""
        self._scene = {}
        for obj in scene.get("objects", []):
            label = obj.get("label") or obj.get("name", "")
            pos   = obj.get("position", (0.0, 0.0))
            if isinstance(pos, (list, tuple)):
                self._scene[label] = (float(pos[0]), float(pos[1]))
        # # Update grey tray position from vision
        # for label in self._scene:
        #     if "grey" in label.lower():
        #         # POSITIONS["grey tray"] = None   # reset — will be set via locate()
        logger.info(f"[UR5] Scene loaded: {list(self._scene.keys())}")

    # ── Public interface ────────────────────────────────────────────────────────

    def locate(self, object_name: str):
        """Return CommandResult confirming object exists."""
        from simulation_backend.mock_robot import CommandResult
        name_lower = object_name.lower()
        for label in self._scene:
            if name_lower in label.lower():
                print(f"  [UR5] LOCATE  '{label}'")
                return CommandResult(success=True, command="locate",
                                     message=f"Found '{label}'")
        return CommandResult(success=False, command="locate",
                             message=f"'{object_name}' not in scene")

    def move_to_object(self, object_name: str):
        """
        Move to approach height above a named slot or object.
        Always lifts to TRANSIT_Z first, then travels laterally, then descends
        to approach height — prevents collisions with the table near top tray slots.
        """
        from simulation_backend.mock_robot import CommandResult
        pose = self._resolve_pose(object_name)
        if pose is None:
            return CommandResult(success=False, command="move",
                                 message=f"No pose for '{object_name}'")
        x, y, z, rx, ry, rz = pose

        # Step 1: lift straight up to transit height at current position
        if self._current_pose is not None:
            cx, cy, cz, crx, cry, crz = self._current_pose
            if TRANSIT_Z > cz + APPROACH_H:   # only lift if we're below transit height
                self._move_to_pose(cx, cy, TRANSIT_Z, crx, cry, crz, label="LIFT")

        # Step 2: travel laterally at transit height to target x, y
        self._move_to_pose(x, y, TRANSIT_Z, rx, ry, rz, label="TRANSIT")

        # Step 3: descend to approach height above target
        self._move_to_pose(x, y, z + APPROACH_H, rx, ry, rz, label=f"APPROACH")

        self._current_pose = pose
        return CommandResult(success=True, command="move",
                             message=f"At approach for '{object_name}'")

    def pick(self, object_name: str):
        """Move to approach, descend, close gripper, ascend."""
        from simulation_backend.mock_robot import CommandResult
        if self._held:
            return CommandResult(success=False, command="pick",
                                 message=f"Already holding '{self._held}'")
        if self._current_pose is None:
            res = self.move_to_object(object_name)
            if not res.success:
                return res

        x, y, z, rx, ry, rz = self._current_pose
        print(f"  [UR5] PICK    '{object_name}'")
        self._gripper_open()
        self._move_to_pose(x, y, z, rx, ry, rz, label="DESCEND", speed_factor=0.5)
        self._gripper_close()
        self._move_to_pose(x, y, z + APPROACH_H, rx, ry, rz, label="ASCEND", speed_factor=0.5)

        self._held = object_name
        return CommandResult(success=True, command="pick",
                             message=f"Picked '{object_name}'")

    def place(self, object_name: str):
        """Move to approach, descend, open gripper, ascend."""
        from simulation_backend.mock_robot import CommandResult
        res = self.move_to_object(object_name)
        if not res.success:
            return res

        x, y, z, rx, ry, rz = self._current_pose
        print(f"  [UR5] PLACE   '{self._held}' → '{object_name}'")
        self._move_to_pose(x, y, z, rx, ry, rz, label="DESCEND", speed_factor=0.5)
        self._gripper_open()
        self._move_to_pose(x, y, z + APPROACH_H, rx, ry, rz, label="ASCEND", speed_factor=0.5)

        self._held = None
        return CommandResult(success=True, command="place",
                             message=f"Placed at '{object_name}'")

    def reset(self) -> None:
        """Return to home joint position."""
        j = HOME_JOINTS
        script = (
            f"movej([{j[0]},{j[1]},{j[2]},{j[3]},{j[4]},{j[5]}], "
            f"a={MOVE_ACCEL}, v={MOVE_SPEED})"
        )
        print("  [UR5] HOME")
        self._send_script(script)
        time.sleep(5.0)
        self._held = None
        self._current_pose = None

    def stop(self) -> None:
        self._send_script("stopj(2.0)")
        logger.warning("[UR5] Emergency stop sent")

    def get_state(self) -> dict:
        return {
            "ip":          self._ip,
            "connected":   self._connected,
            "held_object": self._held,
            "pose":        self._current_pose,
        }

    # ── Motion helpers ──────────────────────────────────────────────────────────

    def _resolve_pose(self, object_name: str) -> Optional[list]:
        """Look up 6D pose for a named object."""
        name_lower = object_name.lower()
        for key, pose in POSITIONS.items():
            if name_lower in key.lower() and pose is not None:
                return pose
        return None

    def _move_to_pose(self, x, y, z, rx, ry, rz,
                      label="MOVE", speed_factor=1.0) -> None:
        v = MOVE_SPEED * speed_factor
        a = MOVE_ACCEL * speed_factor
        script = (
            f"movel(p[{x:.4f},{y:.4f},{z:.4f},"
            f"{rx:.4f},{ry:.4f},{rz:.4f}], "
            f"a={a:.3f}, v={v:.3f}, r={BLEND})"
        )
        print(f"  [UR5] {label:<10} ({x:.3f}, {y:.3f}, {z:.3f})")
        self._send_script(script)
        # Wait proportional to distance (rough estimate)
        time.sleep(2.0 / speed_factor)

    # ── Gripper via Dashboard Server ────────────────────────────────────────────
    # Requires grip_close.urp and grip_open.urp saved on the robot.

    def _gripper_close(self) -> None:
        print(f"  [UR5] GRIP CLOSE")
        self._dashboard("load grip_close.urp")
        time.sleep(0.5)
        self._dashboard("play")
        time.sleep(GRIPPER_WAIT)
        self._dashboard("stop")

    def _gripper_open(self) -> None:
        print(f"  [UR5] GRIP OPEN")
        self._dashboard("load grip_open.urp")
        time.sleep(0.5)
        self._dashboard("play")
        time.sleep(GRIPPER_WAIT)
        self._dashboard("stop")