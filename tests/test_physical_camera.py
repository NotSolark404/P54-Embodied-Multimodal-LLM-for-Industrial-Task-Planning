"""Software-only camera tests. Fake pixels are not hardware evidence."""

import sys
from types import SimpleNamespace

import numpy as np
import pytest

from physical_backend.vision.camera_base import PhysicalFrame
from physical_backend.vision.raspberry_pi_camera import CameraUnavailableError, RaspberryPiCamera
from helper_scripts.capture_calibration_images import main


def test_frame_dimensions_and_color_conversion():
    frame = PhysicalFrame(np.array([[[1, 2, 3]]], dtype=np.uint8), "RGB", 123.0)
    assert (frame.width, frame.height) == (1, 1)
    assert frame.bgr.tolist() == [[[3, 2, 1]]]
    assert frame.rgb.tolist() == [[[1, 2, 3]]]
    assert not hasattr(frame, "depth")
    assert not hasattr(frame, "seg")
    assert not RaspberryPiCamera.capabilities.depth
    assert not RaspberryPiCamera.capabilities.segmentation


@pytest.mark.parametrize("image,order,timestamp", [
    (np.zeros((2, 2, 3)), "RGB", 1),
    (np.zeros((2, 2), dtype=np.uint8), "RGB", 1),
    (np.zeros((0, 2, 3), dtype=np.uint8), "RGB", 1),
    (np.zeros((2, 2, 4), dtype=np.uint8), "RGB", 1),
    (np.zeros((2, 2, 3), dtype=np.uint8), "RGBA", 1),
    (np.zeros((2, 2, 3), dtype=np.uint8), "RGB", float("nan")),
    (np.zeros((2, 2, 3), dtype=np.uint8), "RGB", -1),
])
def test_invalid_frame(image, order, timestamp):
    with pytest.raises(ValueError):
        PhysicalFrame(image, order, timestamp)


def test_missing_dependency_and_script_failure(monkeypatch, tmp_path, capsys):
    monkeypatch.setitem(sys.modules, "picamera2", None)
    camera = RaspberryPiCamera()  # Construction requires no hardware import.
    with pytest.raises(CameraUnavailableError, match="Picamera2/libcamera is unavailable"):
        camera.start()
    camera.close()
    output = tmp_path / "images"
    assert main(["--output", str(output), "--count", "1"]) == 1
    assert "Picamera2/libcamera is unavailable" in capsys.readouterr().err
    assert not output.exists()


class FakeCamera:
    """TEST double only; does not emulate physical calibration."""
    def __init__(self):
        self.events = []

    def create_still_configuration(self, **kwargs):
        return kwargs

    def configure(self, config):
        self.config = config

    def start(self):
        self.events.append("start")

    def capture_array(self, stream):
        assert stream == "main"
        return np.zeros((2, 3, 3), dtype=np.uint8)

    def stop(self):
        self.events.append("stop")

    def close(self):
        self.events.append("close")


@pytest.fixture
def device(monkeypatch):
    fake = FakeCamera()
    monkeypatch.setitem(sys.modules, "picamera2", SimpleNamespace(Picamera2=lambda **kwargs: fake))
    return fake


def test_lifecycle_and_context_cleanup(device):
    camera = RaspberryPiCamera(3, 2)
    with pytest.raises(RuntimeError, match="not started"):
        camera.capture()
    with pytest.raises(ValueError, match="caller failure"):
        with camera:
            camera.start()  # Idempotent.
            frame = camera.capture()
            assert (frame.width, frame.height, frame.color_order) == (3, 2, "BGR")
            assert frame.timestamp > 0
            assert device.config["main"]["format"] == "RGB888"
            raise ValueError("caller failure")
    camera.close()
    assert device.events == ["start", "stop", "close"]
    with pytest.raises(RuntimeError, match="not started"):
        camera.capture()


def test_partial_start_cleanup(device, monkeypatch):
    def fail():
        raise RuntimeError("TEST device unavailable")
    monkeypatch.setattr(device, "start", fail)
    camera = RaspberryPiCamera()
    with pytest.raises(CameraUnavailableError, match="TEST device unavailable"):
        camera.start()
    camera.close()
    assert device.events == ["close"]


def test_close_releases_even_when_stop_fails(device, monkeypatch):
    camera = RaspberryPiCamera()
    camera.start()
    def fail():
        raise RuntimeError("TEST stop failure")
    monkeypatch.setattr(device, "stop", fail)
    with pytest.raises(RuntimeError, match="TEST stop failure"):
        camera.close()
    camera.close()
    assert device.events == ["start", "close"]


def test_capture_failure_cleanup(device, monkeypatch):
    def fail(stream):
        raise OSError("TEST capture failure")
    monkeypatch.setattr(device, "capture_array", fail)
    with pytest.raises(CameraUnavailableError, match="TEST capture failure"):
        with RaspberryPiCamera(3, 2) as camera:
            camera.capture()
    assert device.events == ["start", "stop", "close"]
