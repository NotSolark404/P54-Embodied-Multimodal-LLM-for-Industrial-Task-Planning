import sys
sys.path.insert(0, ".")

from simulation_backend.robots.ur5_script_robot import UR5ScriptRobot, PICK_Z

robot = UR5ScriptRobot()

input("\nPress Enter to move to bottom tray slot 2 (approach height)...")
robot.move_to_object("bottom tray slot 2")
print("  -> pendant TCP should read x=-0.438, y=-0.112")

input("\nIs the arm above SLOT 2 now? Press Enter to run GRIPPER OPEN only...")
robot._gripper_open()
print("  -> arm should NOT have moved")

input("\nDid the arm stay put? Press Enter to DESCEND (no gripper close)...")
x, y, z, rx, ry, rz = robot._current_pose
robot._move_to_pose(x, y, PICK_Z, rx, ry, rz, label="DESCEND", speed_factor=0.5)

input("\nIs it down in slot 2? Press Enter to go back up...")
robot._move_to_pose(x, y, PICK_Z + 0.10, rx, ry, rz, label="ASCEND", speed_factor=0.5)
print("\n── TEST DONE ──")