"""
hello_world.py
--------------
Read-only "hello world" for the physical UR5e over TCP using ur_rtde.

This script NEVER moves the robot. It only:
    1. Loads UR5_IP, UR5_MOVE_SPEED, UR5_MOVE_ACCEL from physical_robot_test/.env
    2. Queries the Dashboard server (port 29999) for version / mode / safety.
    3. Reads joint angles and TCP pose over RTDE (port 30004).

UR5_MOVE_SPEED / UR5_MOVE_ACCEL are loaded and validated here so the config
is checked before the motion test uses them; they are not used to move.

Usage:
    conda activate hello_world_UR5e
    python physical_robot_test/hello_world.py

.env (physical_robot_test/.env):
    UR5_IP=172.21.0.121
    UR5_MOVE_SPEED=0.2     # joint speed, rad/s   (empty -> default)
    UR5_MOVE_ACCEL=0.5     # joint accel, rad/s^2 (empty -> default)

    ## Check for open ports on the robot controller
    # for p in 29999 30002 30004; do timeout 2 bash -c "</dev/tcp/172.21.0.121/$p" && echo "$p open" || echo "$p CLOSED"; done
    # 29999: Dashboard server
    # 30002: Secondary interface
    # 30004: RTDE (for ur_rtde)

    ## Robot info: PolyScope version, model, serial, robot mode, safety status, remote control
    # { printf 'PolyscopeVersion\nget robot model\nget serial number\nrobotmode\nsafetystatus\nis in remote control\n'; sleep 2; } | nc 172.21.0.121 29999
    # remote control MUST BE TRUE Manual network checks (run in a shell, replace the IP):
before any motion command
"""

import math
import os
import sys
from pathlib import Path

import dashboard_client
import rtde_receive
from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parent / ".env"

DEFAULT_MOVE_SPEED = 0.2   # rad/s
DEFAULT_MOVE_ACCEL = 0.5   # rad/s^2
# Conservative ceilings for first tests on real hardware (UR hard limits are much higher).
MAX_MOVE_SPEED = 1.0       # rad/s
MAX_MOVE_ACCEL = 2.0       # rad/s^2

JOINT_NAMES = ["base", "shoulder", "elbow", "wrist1", "wrist2", "wrist3"]

ROBOT_MODES = {
    -1: "NO_CONTROLLER", 0: "DISCONNECTED", 1: "CONFIRM_SAFETY", 2: "BOOTING",
    3: "POWER_OFF", 4: "POWER_ON", 5: "IDLE", 6: "BACKDRIVE", 7: "RUNNING",
    8: "UPDATING_FIRMWARE",
}

SAFETY_MODES = {
    1: "NORMAL", 2: "REDUCED", 3: "PROTECTIVE_STOP", 4: "RECOVERY",
    5: "SAFEGUARD_STOP", 6: "SYSTEM_EMERGENCY_STOP", 7: "ROBOT_EMERGENCY_STOP",
    8: "VIOLATION", 9: "FAULT", 10: "VALIDATE_JOINT_ID", 11: "UNDEFINED_SAFETY_MODE",
    12: "AUTOMATIC_MODE_SAFEGUARD_STOP", 13: "SYSTEM_THREE_POSITION_ENABLING_STOP",
}


def _env_float(name: str, default: float, maximum: float) -> float:
    """Read a positive float from the environment; empty/unset falls back to default."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{name}={raw!r} is not a number")
    if not 0 < value <= maximum:
        raise ValueError(f"{name}={value} must be > 0 and <= {maximum} for testing")
    return value


def load_config() -> tuple[str, float, float]:
    if not ENV_PATH.exists():
        raise FileNotFoundError(f"missing {ENV_PATH}")
    load_dotenv(ENV_PATH)

    ip = os.getenv("UR5_IP", "").strip()
    if not ip:
        raise ValueError(f"UR5_IP is not set in {ENV_PATH}")

    speed = _env_float("UR5_MOVE_SPEED", DEFAULT_MOVE_SPEED, MAX_MOVE_SPEED)
    accel = _env_float("UR5_MOVE_ACCEL", DEFAULT_MOVE_ACCEL, MAX_MOVE_ACCEL)
    return ip, speed, accel


def _safe(call):
    """Run a dashboard query; older PolyScope versions may not support every command."""
    try:
        return call()
    except Exception as e:  # noqa: BLE001 - report and keep going, this is diagnostics
        return f"<unavailable: {e}>"


def read_dashboard(ip: str) -> None:
    print(f"\n[1/2] Dashboard server  {ip}:29999")
    dash = dashboard_client.DashboardClient(ip)
    dash.connect()
    try:
        print(f"  PolyScope version : {_safe(dash.polyscopeVersion)}")
        print(f"  Robot model       : {_safe(dash.getRobotModel)}")
        print(f"  Serial number     : {_safe(dash.getSerialNumber)}")
        print(f"  Robot mode        : {_safe(dash.robotmode)}")
        print(f"  Safety status     : {_safe(dash.safetystatus)}")
        print(f"  Remote control    : {_safe(dash.isInRemoteControl)}")
    finally:
        dash.disconnect()


def read_rtde(ip: str) -> None:
    print(f"\n[2/2] RTDE receive  {ip}:30004")
    rtde_r = rtde_receive.RTDEReceiveInterface(ip)
    try:
        robot_mode = rtde_r.getRobotMode()
        safety_mode = rtde_r.getSafetyMode()
        print(f"  Robot mode        : {robot_mode} ({ROBOT_MODES.get(robot_mode, '?')})")
        print(f"  Safety mode       : {safety_mode} ({SAFETY_MODES.get(safety_mode, '?')})")

        print("\n  Joint positions:")
        for name, q in zip(JOINT_NAMES, rtde_r.getActualQ()):
            print(f"    {name:<8} {q:+.4f} rad  {math.degrees(q):+8.2f} deg")

        x, y, z, rx, ry, rz = rtde_r.getActualTCPPose()
        print("\n  TCP pose (base frame):")
        print(f"    position  x={x * 1000:+.1f}  y={y * 1000:+.1f}  z={z * 1000:+.1f}  mm")
        print(f"    rotvec   rx={rx:+.4f} ry={ry:+.4f} rz={rz:+.4f}  rad")
    finally:
        rtde_r.disconnect()


def main() -> int:
    try:
        ip, speed, accel = load_config()
    except (FileNotFoundError, ValueError) as e:
        print(f"Config error: {e}", file=sys.stderr)
        return 1

    print(f"Hello, UR5e at {ip}  (read-only, no motion)")
    print(f"  Move speed (for motion test) : {speed} rad/s")
    print(f"  Move accel (for motion test) : {accel} rad/s^2")

    try:
        read_dashboard(ip)
        read_rtde(ip)
    except Exception as e:  # noqa: BLE001
        print(f"\nFAILED: {e}", file=sys.stderr)
        print("Check: cable / static IP, `ping`, and that ports 29999 and 30004 are reachable.",
              file=sys.stderr)
        return 1

    print("\nDone. Compare the joint angles above with the pendant's Move tab.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
