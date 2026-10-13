"""Offline-only annotation preparation and leakage safeguards."""
import hashlib
import json

import cv2
import numpy as np
import pytest
import yaml

from fine_tuning.yolov8_real_workspace import annotation as a
from fine_tuning.yolov8_real_workspace import validate_dataset as v


def test_prepare_preserves_sources_and_keeps_one_group(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    for i in range(2):
        cv2.imwrite(str(source / f'{i}.png'), np.full((376, 672, 3), i, np.uint8))
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    records = a.prepare(source, tmp_path / 'work')
    assert len({r['group'] for r in records}) == 1
    assert all(r['split'] is None and not r['reviewed'] for r in records)
    assert before == {p.name: p.read_bytes() for p in source.iterdir()}
    assert not list((tmp_path / 'work').rglob('*.txt'))
    with pytest.raises(FileExistsError):
        a.prepare(source, tmp_path / 'work')


def test_box_normalization():
    row = a.yolo_row(1, [10, 20, 40, 60], 100, 200)
    assert row == '1 0.30000000 0.25000000 0.40000000 0.30000000'
    assert v.parse_labels(row, 2) == [1]
    with pytest.raises(ValueError):
        a.yolo_row(0, [90, 0, 20, 10], 100, 200)


def test_annotation_waits_for_classes(tmp_path):
    config = tmp_path / 'data.yaml'
    config.write_text(yaml.safe_dump(dict(classes_confirmed=False,
                                          object_definitions_confirmed=False)))
    with pytest.raises(ValueError, match='Class names'):
        a.annotate(1, tmp_path, config)


def test_group_leakage_and_manifest_checks(tmp_path):
    files, records = {}, {}
    for split in ['train', 'val']:
        relative = f'images/{split}/frame.png'
        path = tmp_path / relative
        path.parent.mkdir(parents=True)
        path.write_bytes(split.encode())
        files[relative] = path
        records[relative] = dict(group='same_scene', sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    manifest = tmp_path / 'split_groups.json'
    manifest.write_text(json.dumps(records))
    with pytest.raises(ValueError, match='split leakage'):
        v.validate_groups(tmp_path, files)
    records['images/val/frame.png']['group'] = 'independent_scene'
    manifest.write_text(json.dumps(records))
    v.validate_groups(tmp_path, files)
    files['images/train/frame.png'].write_bytes(b'changed')
    with pytest.raises(ValueError, match='checksum'):
        v.validate_groups(tmp_path, files)
    manifest.write_text('{}')
    with pytest.raises(ValueError, match='exactly every'):
        v.validate_groups(tmp_path, files)


def test_annotation_confirmation_blocks_acceptance(tmp_path):
    config = tmp_path / 'data.yaml'
    config.write_text(yaml.safe_dump(dict(classes_confirmed=True, names=['tray'],
                                         annotations_confirmed=False)))
    report = v.validate_dataset(config)
    assert any('annotations require confirmation' in error for error in report.errors)


def test_confirmed_classes_allow_draft_without_final_review(tmp_path):
    config = tmp_path / 'data.yaml'
    config.write_text(yaml.safe_dump(dict(classes_confirmed=True,
        names=['automatic_pick_tray', 'electronic_component'],
        object_definitions_confirmed=False, annotations_confirmed=False)))
    (tmp_path / 'inventory.json').write_text('[]')
    # Reaches inventory validation without launching any GUI.
    with pytest.raises(ValueError, match='index is out of range'):
        a.annotate(1, tmp_path, config)
