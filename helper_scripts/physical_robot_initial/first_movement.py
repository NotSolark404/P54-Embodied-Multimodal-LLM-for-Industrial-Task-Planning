"""
first_movement.py
-----------------
First motion test for the physical UR5e using ur_rtde.

Rotates ONLY wrist 3 (the tool flange) by 90 degrees, then returns to the
exact starting joint position. The arm itself does not change position.

Safety checks before any motion:
    - Robot must be RUNNING (powered on, brakes released) with safety NORMAL.
    - Robot must be in Remote Control mode.
    - You must type "yes" at the prompt.

Before running:
    - Pendant speed slider at 10-25 %.
    - Clear area around the tool; tidy any loose tool cable.
    - Someone with a hand on the e-stop.

Usage:
    conda activate hello_world_UR5e
    python physical_robot_test/first_movement.py

Config comes from physical_robot_test/.env (same as hello_world.py):
    UR5_IP, UR5_MOVE_SPEED (rad/s), UR5_MOVE_ACCEL (rad/s^2)
"""

import math
import sys

import dashboard_client
import rtde_control
import rtde_receive

from hello_world import JOINT_NAMES, ROBOT_MODES, SAFETY_MODES, load_config

WRIST3 = 5                      # joint index of wrist 3
ROTATION_DEG = 90.0             # how far wrist 3 turns
WRIST3_LIMIT_RAD = 2 * math.pi  # UR5e wrist 3 range is +/-360 deg
RETURN_TOL_DEG = 0.5            # max allowed error after returning to start

ROBOT_MODE_RUNNING = 7
SAFETY_MODE_NORMAL = 1


def print_joints(label: str, q: list[float]) -> None:
    print(f"  {label}:")
    for name, value in zip(JOINT_NAMES, q):
        print(f"    {name:<8} {math.degrees(value):+8.2f} deg")


def check_remote_control(ip: str) -> bool:
    dash = dashboard_client.DashboardClient(ip)
    dash.connect()
    try:
        return dash.isInRemoteControl()
    except Exception as e:  # noqa: BLE001 - older PolyScope lacks this command
        print(f"  (could not query remote control: {e}; continuing)")
        return True
    finally:
        dash.disconnect()


def preflight(rtde_r: rtde_receive.RTDEReceiveInterface, ip: str) -> bool:
    robot_mode = rtde_r.getRobotMode()
    safety_mode = rtde_r.getSafetyMode()
    print(f"  Robot mode  : {robot_mode} ({ROBOT_MODES.get(robot_mode, '?')})")
    print(f"  Safety mode : {safety_mode} ({SAFETY_MODES.get(safety_mode, '?')})")

    if safety_mode != SAFETY_MODE_NORMAL:
        print("ABORT: safety mode is not NORMAL. Clear the stop on the pendant first.")
        return False
    if robot_mode != ROBOT_MODE_RUNNING:
        print("ABORT: robot is not RUNNING. Power on and release brakes on the pendant first.")
        return False
    if not check_remote_control(ip):
        print("ABORT: robot is in Local mode. Switch to Remote Control on the pendant.")
        return False
    return True


def main() -> int:
    try:
        ip, speed, accel = load_config()
    except (FileNotFoundError, ValueError) as e:
        print(f"Config error: {e}", file=sys.stderr)
        return 1

    print(f"UR5e first movement test  {ip}")
    print(f"  Speed {speed} rad/s, accel {accel} rad/s^2")

    rtde_r = rtde_receive.RTDEReceiveInterface(ip)
    rtde_c = None
    try:
        if not preflight(rtde_r, ip):
            return 1

        start_q = rtde_r.getActualQ()
        print_joints("Start position", start_q)

        # Turn the direction that stays inside wrist 3's joint range.
        delta = math.radians(ROTATION_DEG)
        if start_q[WRIST3] + delta > WRIST3_LIMIT_RAD:
            delta = -delta
        target_q = list(start_q)
        target_q[WRIST3] += delta

        print(f"\nPlan: wrist 3 {math.degrees(delta):+.1f} deg, then back to start.")
        print("Speed slider low? Area clear? Hand on the e-stop?")
        if input('Type "yes" to move: ').strip().lower() != "yes":
            print("Cancelled. Robot not moved.")
            return 0

        rtde_c = rtde_control.RTDEControlInterface(ip)

        print("\nMoving to target...")
        if not rtde_c.moveJ(target_q, speed, accel):
            print("moveJ to target failed (check pendant for errors).")
            return 1
        print_joints("Reached", rtde_r.getActualQ())

        print("\nReturning to start...")
        if not rtde_c.moveJ(start_q, speed, accel):
            print("moveJ back to start failed (check pendant for errors).")
            return 1

        end_q = rtde_r.getActualQ()
        print_joints("End position", end_q)

        max_err = max(abs(math.degrees(a - b)) for a, b in zip(start_q, end_q))
        if max_err > RETURN_TOL_DEG:
            print(f"\nWARNING: end differs from start by {max_err:.2f} deg.")
            return 1
        print(f"\nSUCCESS: returned to start (max error {max_err:.3f} deg).")
        return 0

    except KeyboardInterrupt:
        print("\nInterrupted: stopping robot.")
        if rtde_c is not None:
            rtde_c.stopJ(accel)
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"\nFAILED: {e}", file=sys.stderr)
        return 1
    finally:
        if rtde_c is not None:
            rtde_c.stopScript()
            rtde_c.disconnect()
        rtde_r.disconnect()


if __name__ == "__main__":
    sys.exit(main())
