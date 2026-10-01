"""
simulation_backend/robots/
--------------------------
Real robot implementations.
Selected at runtime by ROBOT_MODEL in .env (mock | franka | kuka) — see
Simulation._load_robot() in simulation_backend/simulation.py.

Available:
    from simulation_backend.robots.Kuka_IIWA    import KukaIIWA
    from simulation_backend.robots.Franka_panda import FrankaPanda

UR5 is not yet implemented — ROBOT_MODEL=ur5 falls back to MockRobot.
"""