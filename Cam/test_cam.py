"""Software-only checks for the visually confirmed ZED side-by-side layout."""
from unittest.mock import Mock

import numpy as np
import pytest

from Cam import cam


def stereo_frame():
    frame = np.empty((*cam.CONFIRMED_STEREO_SHAPE, 3), dtype=np.uint8)
    frame[:, :672] = [10, 20, 30]  # Left BGR
    frame[:, 672:] = [100, 150, 200]  # Distinct right BGR
    return frame


def test_left_selection_dimensions_and_rgb():
    source = stereo_frame()
    result = cam.left_frame_rgb(source)
    assert result.shape == (376, 672, 3)
    np.testing.assert_array_equal(result, np.broadcast_to([30, 20, 10], result.shape))
    np.testing.assert_array_equal(source[:, 672:], np.broadcast_to([100, 150, 200], result.shape))


@pytest.mark.parametrize("frame", [None, [], np.zeros((0, 1344, 3), dtype=np.uint8),
    np.zeros((376, 1344), dtype=np.uint8), np.zeros((376, 1344, 4), dtype=np.uint8),
    np.zeros((376, 1344, 3), dtype=np.float32)])
def test_invalid_frames(frame):
    with pytest.raises(RuntimeError, match="Missing frame|Invalid ZED frame"):
        cam.left_frame_rgb(frame)


@pytest.mark.parametrize("width", [672, 1343, 1280])
def test_unconfirmed_layout(width):
    with pytest.raises(RuntimeError, match="Unconfirmed ZED frame layout"):
        cam.left_frame_rgb(np.zeros((376, width, 3), dtype=np.uint8))


@pytest.mark.parametrize("opened,ret,frame,error", [
    (True, True, stereo_frame(), None),
    (False, False, None, "Cannot open RTSP"),
    (True, False, None, "Failed to read frame"),
    (True, True, None, "Missing frame"),
])
def test_capture_and_release(monkeypatch, opened, ret, frame, error):
    cap = Mock()
    cap.isOpened.return_value = opened
    cap.read.return_value = (ret, frame)
    factory = Mock(return_value=cap)
    monkeypatch.setattr(cam.cv2, "VideoCapture", factory)
    if error:
        with pytest.raises(RuntimeError, match=error):
            cam.capture_frame()
    else:
        np.testing.assert_array_equal(cam.capture_frame(), cam.left_frame_rgb(frame))
        assert cap.read.call_count == 6
    factory.assert_called_once_with(cam.RTSP_URL, cam.cv2.CAP_FFMPEG)
    cap.release.assert_called_once()


def test_save_left_frame(tmp_path, monkeypatch):
    path = tmp_path / "test_frame_left.jpg"
    monkeypatch.setattr(cam, "LEFT_FRAME_PATH", path)
    cam.save_left_frame(cam.left_frame_rgb(stereo_frame()))
    saved = cam.cv2.imread(str(path))
    assert saved.shape == (376, 672, 3)
    np.testing.assert_allclose(saved[0, 0], [10, 20, 30], atol=2)


def test_save_failure(monkeypatch):
    monkeypatch.setattr(cam.cv2, "imwrite", lambda *args: False)
    with pytest.raises(RuntimeError, match="Failed to save"):
        cam.save_left_frame(cam.left_frame_rgb(stereo_frame()))
