# import sys
# sys.path.insert(0, ".")

# from simulation_backend.robots.ur5_script_robot import UR5ScriptRobot

# robot = UR5ScriptRobot()

# print("\n── MOVE TO PICK ──")
# robot.move_to_object("bottom tray slot 2")

# print("\n── PICK ──")
# robot.pick("grey tray")   # picks at bottom tray slot 2 (current location)

# print("\n── PLACE ──")
# robot.place("top tray slot 1")   # moves there itself, then places

# print("\n── DONE ──")

# import sys
# sys.path.insert(0, ".")

# from simulation_backend.robots.ur5_script_robot import UR5ScriptRobot

# robot = UR5ScriptRobot()

# print("\n── PICK ──")
# robot.pick("grey tray")          # moves to grey tray coordinates, then picks

# print("\n── PLACE ──")
# robot.place("top tray slot 1")   # moves to top tray slot 1, then places

# print("\n── DONE ──")



import sys
sys.path.insert(0, ".")

from simulation_backend.robots.ur5_script_robot import UR5ScriptRobot

robot = UR5ScriptRobot()

print("\n── PICK ──")
robot.pick("top tray slot 1")       # moves to top tray slot 1, then picks

print("\n── PLACE ──")
robot.place("bottom tray slot 3")   # moves to bottom tray slot 3, then places

print("\n── DONE ──")