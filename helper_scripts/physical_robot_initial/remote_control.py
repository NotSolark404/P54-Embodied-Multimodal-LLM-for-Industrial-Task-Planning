"""
remote_control.py
-----------------
Keyboard teleoperation of the physical UR5e from the terminal.

Each key press moves the robot ONE small step, then waits. Holding a key
gives repeated steps. Keys pressed while the robot is moving are discarded,
so moves never pile up.

Keys:
    w / s   TCP +X / -X   (base frame, linear move, height kept)
    a / d   TCP +Y / -Y
    z / x   rotate base joint + / -
    q / e   rotate wrist 3 (tool flange) + / -
    r       return to home (asks y to confirm)
    p       quit

Safety:
    - Same preflight as first_movement.py (RUNNING, safety NORMAL, Remote Control).
    - Base / wrist 3 may not rotate further than JOINT_LIMIT_DEG from their home angles.
    - Each target is checked against the robot's own safety limits.
    - Moves are short and blocking: Ctrl+C takes effect after the current step,
      so keep a hand on the e-stop.

If w/s/a/d move in an unexpected direction for how the robot is mounted,
swap the vectors in TRANSLATION_KEYS.

Usage:
    conda activate hello_world_UR5e
    python physical_robot_test/remote_control.py

.env (in addition to UR5_IP / UR5_MOVE_SPEED / UR5_MOVE_ACCEL, used for z/x/q/e/r):
    UR5_LINEAR_SPEED=0.05   # m/s,   w/s/a/d   (max 0.25)
    UR5_LINEAR_ACCEL=0.25   # m/s^2, w/s/a/d   (max 1.2)
"""

import math
import sys
import termios
import tty
from dataclasses import dataclass

import rtde_control
import rtde_receive

from first_movement import preflight
from hello_world import _env_float, load_config
from home_position import HOME_Q

STEP_M = 0.01                 # 10 mm per key press
QUIT_KEY = "p"

# Linear (w/s/a/d) settings, read from .env: (env name, default, max allowed)
LINEAR_SPEED_ENV = ("UR5_LINEAR_SPEED", 0.05, 0.25)   # m/s
LINEAR_ACCEL_ENV = ("UR5_LINEAR_ACCEL", 0.25, 1.2)    # m/s^2

BASE, WRIST3 = 0, 5           # joint indices
JOINT_NAMES = {BASE: "base", WRIST3: "wrist 3"}
JOINT_STEP_DEG = {BASE: 5.0, WRIST3: 10.0}      # per key press
JOINT_LIMIT_DEG = {BASE: 90.0, WRIST3: 180.0}   # max rotation away from home angle

# key -> (dx, dy) unit direction in the robot base frame
TRANSLATION_KEYS = {
    "w": (1, 0),
    "s": (-1, 0),
    "a": (0, 1),
    "d": (0, -1),
}
# key -> (joint index, rotation direction)
JOINT_KEYS = {
    "z": (BASE, 1),
    "x": (BASE, -1),
    "q": (WRIST3, 1),
    "e": (WRIST3, -1),
}

HELP = (
    "\n  w/s: X +/-   a/d: Y +/-   z/x: base +/-   q/e: wrist +/-   r: home   p: quit\n"
    f"  step {STEP_M * 1000:.0f} mm, base {JOINT_STEP_DEG[BASE]:.0f} deg, "
    f"wrist {JOINT_STEP_DEG[WRIST3]:.0f} deg\n"
)


def read_key() -> str:
    return sys.stdin.read(1).lower()


def flush_keys() -> None:
    """Drop key presses that arrived while the robot was moving."""
    termios.tcflush(sys.stdin, termios.TCIFLUSH)


def status(rtde_r: rtde_receive.RTDEReceiveInterface) -> None:
    x, y, z = rtde_r.getActualTCPPose()[:3]
    q = rtde_r.getActualQ()
    print(f"  TCP x={x * 1000:+7.1f} y={y * 1000:+7.1f} z={z * 1000:+7.1f} mm"
          f"   base {math.degrees(q[BASE]):+7.2f}  wrist3 {math.degrees(q[WRIST3]):+7.2f} deg",
          flush=True)


@dataclass
class LinearConfig:
    speed: float       # m/s
    accel: float       # m/s^2


def load_linear_config() -> LinearConfig:
    """Read linear-move settings; call after load_config() has loaded .env."""
    return LinearConfig(
        speed=_env_float(*LINEAR_SPEED_ENV),
        accel=_env_float(*LINEAR_ACCEL_ENV),
    )


def within_limit(new: float, old: float, limit: float) -> bool:
    """Allow a move if it stays inside the limit or moves back toward zero."""
    return abs(new) <= limit or abs(new) < abs(old)


def translate(rtde_c, rtde_r, lin: LinearConfig, dx: int, dy: int) -> None:
    target = list(rtde_r.getActualTCPPose())
    target[0] += dx * STEP_M
    target[1] += dy * STEP_M

    if not rtde_c.isPoseWithinSafetyLimits(target):
        print("  blocked: target outside robot safety limits")
        return
    if not rtde_c.moveL(target, lin.speed, lin.accel):
        print("  moveL failed (check pendant)")


def rotate_joint(rtde_c, rtde_r, joint: int, direction: int,
                 speed: float, accel: float) -> None:
    q = rtde_r.getActualQ()
    target = list(q)
    target[joint] += direction * math.radians(JOINT_STEP_DEG[joint])

    if not within_limit(target[joint] - HOME_Q[joint], q[joint] - HOME_Q[joint],
                        math.radians(JOINT_LIMIT_DEG[joint])):
        print(f"  blocked: {JOINT_NAMES[joint]} would exceed "
              f"{JOINT_LIMIT_DEG[joint]:.0f} deg from home")
        return
    if not rtde_c.moveJ(target, speed, accel):
        print("  moveJ failed (check pendant)")


def go_home(rtde_c, speed: float, accel: float) -> None:
    print("  Move to home? press y to confirm, any other key cancels", flush=True)
    if read_key() != "y":
        print("  home cancelled")
        return
    print("  moving home...", flush=True)
    if not rtde_c.moveJ(HOME_Q, speed, accel):
        print("  moveJ home failed (check pendant)")


def run(rtde_c, rtde_r, speed: float, accel: float, lin: LinearConfig) -> None:
    print(HELP)
    status(rtde_r)

    while True:
        key = read_key()
        if key == QUIT_KEY:
            return
        if key in TRANSLATION_KEYS:
            translate(rtde_c, rtde_r, lin, *TRANSLATION_KEYS[key])
        elif key in JOINT_KEYS:
            rotate_joint(rtde_c, rtde_r, *JOINT_KEYS[key], speed, accel)
        elif key == "r":
            go_home(rtde_c, speed, accel)
        else:
            continue
        status(rtde_r)
        flush_keys()


def main() -> int:
    try:
        ip, speed, accel = load_config()
        lin = load_linear_config()
    except (FileNotFoundError, ValueError) as e:
        print(f"Config error: {e}", file=sys.stderr)
        return 1

    print(f"UR5e keyboard remote control  {ip}")
    print(f"  Joint moves : {speed} rad/s, {accel} rad/s^2")
    print(f"  Linear moves: {lin.speed} m/s, {lin.accel} m/s^2")
    rtde_r = rtde_receive.RTDEReceiveInterface(ip)
    rtde_c = None
    old_term = termios.tcgetattr(sys.stdin)
    try:
        if not preflight(rtde_r, ip):
            return 1
        print("Speed slider low? Area clear? Hand on the e-stop?")
        if input('Type "yes" to start remote control: ').strip().lower() != "yes":
            print("Cancelled. Robot not moved.")
            return 0

        rtde_c = rtde_control.RTDEControlInterface(ip)
        tty.setcbreak(sys.stdin)   # single key reads, Ctrl+C still works
        run(rtde_c, rtde_r, speed, accel, lin)
        print("\nQuit.")
        return 0

    except KeyboardInterrupt:
        print("\nInterrupted: stopping robot.")
        if rtde_c is not None:
            rtde_c.stopL(lin.accel)
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"\nFAILED: {e}", file=sys.stderr)
        return 1
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_term)
        if rtde_c is not None:
            rtde_c.stopScript()
            rtde_c.disconnect()
        rtde_r.disconnect()


if __name__ == "__main__":
    sys.exit(main())
