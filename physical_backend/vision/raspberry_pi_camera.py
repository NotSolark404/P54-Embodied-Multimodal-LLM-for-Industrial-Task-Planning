"""Optional Picamera2 adapter. Physical hardware validation is pending."""

import time

from .camera_base import CameraBase, PhysicalFrame


class CameraUnavailableError(RuntimeError):
    """The physical camera or its platform dependencies cannot be opened."""


class RaspberryPiCamera(CameraBase):
    def __init__(self, width: int = 640, height: int = 480, camera_num: int = 0):
        for name, value, minimum in (("width", width, 1), ("height", height, 1), ("camera_num", camera_num, 0)):
            if type(value) is not int or value < minimum:
                raise ValueError(f"{name} must be an integer >= {minimum}")
        self.width, self.height = width, height
        self.camera_num = camera_num
        self._camera = None

    def start(self) -> None:
        if self._camera is not None:
            return
        try:
            from picamera2 import Picamera2
        except (ImportError, OSError) as exc:
            raise CameraUnavailableError(
                "Picamera2/libcamera is unavailable. Install the Raspberry Pi camera "
                "stack on the target Pi and connect a camera; no simulation fallback is provided."
            ) from exc

        camera = None
        try:
            camera = Picamera2(camera_num=self.camera_num)
            # Picamera2 RGB888 arrays use OpenCV's B,G,R byte order.
            config = camera.create_still_configuration(
                main={"size": (self.width, self.height), "format": "RGB888"}
            )
            camera.configure(config)
            camera.start()
        except Exception as exc:
            if camera is not None:
                try:
                    camera.close()
                except Exception:
                    pass  # Preserve the original opening error.
            raise CameraUnavailableError(
                f"Cannot start physical Raspberry Pi camera {self.camera_num}: {exc}"
            ) from exc
        self._camera = camera

    def capture(self) -> PhysicalFrame:
        if self._camera is None:
            raise RuntimeError("Camera is not started; call start() before capture()")
        try:
            image = self._camera.capture_array("main").copy()
        except Exception as exc:
            raise CameraUnavailableError(f"Physical camera capture failed: {exc}") from exc
        frame = PhysicalFrame(image, "BGR", time.time())
        if (frame.width, frame.height) != (self.width, self.height):
            raise RuntimeError("Camera returned a different resolution than requested")
        return frame

    def close(self) -> None:
        camera, self._camera = self._camera, None
        if camera is not None:
            try:
                camera.stop()
            finally:
                camera.close()
