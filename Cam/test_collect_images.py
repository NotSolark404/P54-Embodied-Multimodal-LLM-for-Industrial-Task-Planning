"""Hardware-free collection checks; all captures are synthetic."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
import pytest

from Cam import cam, collect_images as collector


@pytest.fixture
def capture(monkeypatch):
    stereo = np.empty((376, 1344, 3), dtype=np.uint8)
    stereo[:, :672] = [10, 20, 30]
    stereo[:, 672:] = [100, 150, 200]
    fake = Mock(side_effect=lambda: cam.left_frame_rgb(stereo))
    monkeypatch.setattr(cam, "capture_frame", fake)
    return fake


def test_batch_pixels_names_and_delay(tmp_path, monkeypatch, capture):
    sleep = Mock()
    monkeypatch.setattr(collector.time, "sleep", sleep)
    paths = collector.collect_images(3, 2, tmp_path)
    assert len(set(paths)) == capture.call_count == 3
    assert sleep.call_count == 2
    sleep.assert_called_with(2)
    for path in paths:
        assert path.name.startswith("zed_left_") and "Z_" in path.name
        image = cv2.imread(str(path))
        assert image.shape == (376, 672, 3)
        np.testing.assert_array_equal(image, np.broadcast_to([10, 20, 30], image.shape))


def test_collision_preserves_file(tmp_path, monkeypatch, capture):
    monkeypatch.setattr(collector, "datetime", SimpleNamespace(
        now=lambda tz: datetime(2026, 1, 1, tzinfo=timezone.utc)))
    monkeypatch.setattr(collector, "uuid4", lambda: SimpleNamespace(hex="fixed"))
    path = collector.collect_images(1, 0, tmp_path)[0]
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        collector.collect_images(1, 0, tmp_path)
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("count,interval", [(0, 1), (-1, 1), (1, -1),
    (1, float("nan")), (1, float("inf"))])
def test_invalid_arguments_before_capture(tmp_path, capture, count, interval):
    with pytest.raises(ValueError):
        collector.collect_images(count, interval, tmp_path / "unused")
    capture.assert_not_called()
    assert not (tmp_path / "unused").exists()


@pytest.mark.parametrize("failure,code", [(RuntimeError("No frame"), 1), (KeyboardInterrupt(), 130)])
def test_failure_retains_completed_images(tmp_path, capture, failure, code):
    frame = capture()
    capture.side_effect = [frame, failure]
    assert collector.main(["--count", "3", "--interval", "0", "--output", str(tmp_path)]) == code
    assert len(list(tmp_path.glob("*.png"))) == 1


def test_encoding_failure_creates_no_file(tmp_path, monkeypatch, capture):
    monkeypatch.setattr(cv2, "imencode", lambda *args: (False, None))
    with pytest.raises(RuntimeError, match="encode"):
        collector.collect_images(1, 0, tmp_path)
    assert not list(tmp_path.iterdir())


def test_missing_image_creates_no_file(tmp_path, capture):
    capture.side_effect = None
    capture.return_value = None
    with pytest.raises(RuntimeError, match="Invalid captured"):
        collector.collect_images(1, 0, tmp_path)
    assert not list(tmp_path.iterdir())


def test_write_failure_removes_partial_file(tmp_path, monkeypatch, capture):
    original_open = collector.Path.open

    class BrokenWriter:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def write(self, data):
            self.handle.write(data[:10])
            raise OSError("disk full")

        def __exit__(self, *args):
            self.handle.close()

    def broken_open(path, mode="r", *args, **kwargs):
        handle = original_open(path, mode, *args, **kwargs)
        return BrokenWriter(handle) if mode == "xb" else handle

    monkeypatch.setattr(collector.Path, "open", broken_open)
    with pytest.raises(OSError, match="disk full"):
        collector.collect_images(1, 0, tmp_path)
    assert not list(tmp_path.iterdir())
