"""
home_position.py
----------------
Move the physical UR5e back to its standard home (base) joint position.

Uses a joint-space move (moveJ): every joint rotates directly to its home
angle. The TCP does NOT follow a straight line, so check the path is clear
when the arm is far from home.

Safety checks before any motion (shared with first_movement.py):
    - Robot must be RUNNING with safety NORMAL, in Remote Control mode.
    - Per-joint distance to home is printed; you must type "yes".

Usage:
    conda activate hello_world_UR5e
    python physical_robot_test/home_position.py

Config comes from physical_robot_test/.env: UR5_IP, UR5_MOVE_SPEED, UR5_MOVE_ACCEL
"""

import math
import sys

import rtde_control
import rtde_receive

from first_movement import RETURN_TOL_DEG, preflight, print_joints
from hello_world import JOINT_NAMES, load_config

# Standard home position of the arm (radians), recorded from the robot.
HOME_Q = [-1.568847, -2.343778, 2.104474, -1.361051, -1.565358, -4.708451]

ALREADY_HOME_DEG = 0.5   # skip the move if every joint is this close to home
LARGE_MOVE_DEG = 90.0    # warn if any joint has to travel further than this


def main() -> int:
    try:
        ip, speed, accel = load_config()
    except (FileNotFoundError, ValueError) as e:
        print(f"Config error: {e}", file=sys.stderr)
        return 1

    print(f"UR5e move to home  {ip}")
    print(f"  Speed {speed} rad/s, accel {accel} rad/s^2")

    rtde_r = rtde_receive.RTDEReceiveInterface(ip)
    rtde_c = None
    try:
        if not preflight(rtde_r, ip):
            return 1

        current_q = rtde_r.getActualQ()
        deltas = [math.degrees(h - c) for h, c in zip(HOME_Q, current_q)]

        print("\n  Joint      current      home     travel")
        for name, c, h, d in zip(JOINT_NAMES, current_q, HOME_Q, deltas):
            print(f"    {name:<8} {math.degrees(c):+8.2f}  {math.degrees(h):+8.2f}  {d:+8.2f} deg")

        max_travel = max(abs(d) for d in deltas)
        if max_travel <= ALREADY_HOME_DEG:
            print("\nAlready at home. Nothing to do.")
            return 0

        if max_travel > LARGE_MOVE_DEG:
            print(f"\nWARNING: a joint travels {max_travel:.1f} deg. "
                  "The arm will sweep a large path; make sure it is clear.")
        print(f"Estimated time: ~{math.radians(max_travel) / speed:.0f} s at {speed} rad/s.")
        print("Speed slider low? Path clear? Hand on the e-stop?")
        if input('Type "yes" to move home: ').strip().lower() != "yes":
            print("Cancelled. Robot not moved.")
            return 0

        rtde_c = rtde_control.RTDEControlInterface(ip)

        print("\nMoving to home...")
        if not rtde_c.moveJ(HOME_Q, speed, accel):
            print("moveJ to home failed (check pendant for errors).")
            return 1

        end_q = rtde_r.getActualQ()
        print_joints("End position", end_q)

        max_err = max(abs(math.degrees(a - b)) for a, b in zip(HOME_Q, end_q))
        if max_err > RETURN_TOL_DEG:
            print(f"\nWARNING: end differs from home by {max_err:.2f} deg.")
            return 1
        print(f"\nSUCCESS: at home (max error {max_err:.3f} deg).")
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
