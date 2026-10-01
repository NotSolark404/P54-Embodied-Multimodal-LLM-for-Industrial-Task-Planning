"""
realsense_camera.py
-------------------
Intel RealSense D435 driver.
pip install pyrealsense2
"""
import numpy as np
import logging
from camera_backend.camera_interface import CameraFrame

logger = logging.getLogger(__name__)


class RealSenseCamera:
    def __init__(self, width=1280, height=720, fps=30):
        import pyrealsense2 as rs
        self.pipeline = rs.pipeline()
        config = rs.config()
        config.enable_stream(rs.stream.color, width, height, rs.format.bgr8, fps)
        config.enable_stream(rs.stream.depth, width, height, rs.format.z16, fps)
        self.align   = rs.align(rs.stream.color)
        self.profile = self.pipeline.start(config)
        self._get_intrinsics()
        logger.info(f"[RealSense] Started {width}x{height}@{fps}fps")

    def _get_intrinsics(self):
        import pyrealsense2 as rs
        stream = self.profile.get_stream(rs.stream.color)
        intr   = stream.as_video_stream_profile().get_intrinsics()
        self.intrinsics = {
            "fx": intr.fx, "fy": intr.fy,
            "cx": intr.ppx, "cy": intr.ppy,
        }

    def get_frame(self) -> CameraFrame:
        frames  = self.pipeline.wait_for_frames()
        aligned = self.align.process(frames)
        rgb     = np.asanyarray(aligned.get_color_frame().get_data())
        depth   = np.asanyarray(aligned.get_depth_frame().get_data()).astype(np.float32) / 1000.0
        return CameraFrame(rgb=rgb, depth=depth, intrinsics=self.intrinsics)

    def pixel_to_3d(self, u: int, v: int, depth_m: float) -> tuple:
        fx = self.intrinsics["fx"]
        fy = self.intrinsics["fy"]
        cx = self.intrinsics["cx"]
        cy = self.intrinsics["cy"]
        return ((u-cx)*depth_m/fx, (v-cy)*depth_m/fy, depth_m)

    def stop(self):
        self.pipeline.stop()