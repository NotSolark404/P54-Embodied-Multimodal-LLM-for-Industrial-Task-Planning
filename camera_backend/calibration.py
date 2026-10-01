"""
calibration.py
--------------
Camera-to-robot coordinate calibration.
Run once in the lab with known point pairs.

Usage:
    python -m camera_backend.calibration
"""
import numpy as np
import os
import logging

logger = logging.getLogger(__name__)

CALIBRATION_FILE = os.path.join(os.path.dirname(__file__), "camera_to_robot.npy")


def load_transform() -> np.ndarray:
    if not os.path.exists(CALIBRATION_FILE):
        logger.warning("No calibration file — using identity transform. Run calibration first.")
        return np.eye(4)
    return np.load(CALIBRATION_FILE)


def camera_to_robot_coords(x_cam: float, y_cam: float, z_cam: float) -> tuple:
    T      = load_transform()
    p_cam  = np.array([x_cam, y_cam, z_cam, 1.0])
    p_robot = T @ p_cam
    return (float(p_robot[0]), float(p_robot[1]), float(p_robot[2]))


def calibrate():
    print("=== Camera-to-Robot Calibration ===")
    print("Move the robot tip to visible points. Record both robot XYZ and camera XYZ.\n")

    robot_pts, camera_pts = [], []
    n = int(input("Number of calibration points (minimum 4): "))

    for i in range(n):
        print(f"\nPoint {i+1}:")
        rx = float(input("  Robot X (m): "))
        ry = float(input("  Robot Y (m): "))
        rz = float(input("  Robot Z (m): "))
        cx = float(input("  Camera X (m): "))
        cy = float(input("  Camera Y (m): "))
        cz = float(input("  Camera Z (m): "))
        robot_pts.append([rx, ry, rz])
        camera_pts.append([cx, cy, cz])

    R = np.array(robot_pts)
    C = np.array(camera_pts)
    R_c = C.mean(axis=0)
    R_r = R.mean(axis=0)
    H   = (C - R_c).T @ (R - R_r)
    U, S, Vt = np.linalg.svd(H)
    rot = Vt.T @ U.T
    t   = R_r - rot @ R_c

    T = np.eye(4)
    T[:3, :3] = rot
    T[:3, 3]  = t

    np.save(CALIBRATION_FILE, T)
    print(f"\nCalibration saved to {CALIBRATION_FILE}")
    print(f"Transform:\n{T}")


if __name__ == "__main__":
    calibrate()