"""Software preparation tests only: no camera, measured fixture, or robot."""
import json

import pytest
from pydantic import ValidationError

from physical_backend.workspace import (
    DEFAULT_CONFIG, Region, TargetRejected, Workspace, load_workspace, require_valid_target,
)


def data():
    return json.loads(DEFAULT_CONFIG.read_text())


def test_identity_and_unknown_measurements():
    workspace = load_workspace()
    assert [(t.id, t.name, t.reference_photo_location) for t in workspace.trays] == [
        ('automatic_pick_1', 'Automatic Pick 1', 'lower'),
        ('automatic_pick_2', 'Automatic Pick 2', 'upper'),
    ]
    assert len({c.id for t in workspace.trays for c in t.compartments}) == 8
    assert workspace.camera.model is None
    assert workspace.camera.sdk_configuration_record is None
    assert all(v is None for v in workspace.measurements.model_dump().values())
    assert all(t.boundary is None for t in workspace.trays)
    assert all(c.boundary is None and c.valid_pick_region is None and c.valid_place_region is None
               for t in workspace.trays for c in t.compartments)


@pytest.mark.parametrize('tray_index', [0, 1])
@pytest.mark.parametrize('slot', ['left_1', 'left_2', 'right_1', 'right_2'])
@pytest.mark.parametrize('action', ['pick', 'place'])
def test_all_targets_rejected(tray_index, slot, action):
    workspace = load_workspace()
    tray = workspace.trays[tray_index]
    message = 'prohibited' if slot.startswith('right') else 'Missing physical measurements'
    with pytest.raises(TargetRejected, match=message):
        require_valid_target(workspace, tray.id, f'{tray.id}/{slot}', action)


@pytest.mark.parametrize('mutation', [
    lambda d: d['trays'].__setitem__(1, d['trays'][0]),
    lambda d: d['trays'][0].update(id='unknown'),
    lambda d: d['trays'][0].update(reference_photo_location='upper'),
    lambda d: d['trays'][0]['compartments'].pop(),
    lambda d: d['trays'][0]['compartments'].__setitem__(1, d['trays'][0]['compartments'][0]),
    lambda d: d['trays'][0]['compartments'][0].update(id='automatic_pick_2/left_1'),
    lambda d: d['trays'][0]['compartments'][2].update(usage='candidate_pending_lab_confirmation'),
    lambda d: d['trays'][0]['compartments'][2].update(pick_allowed=True),
    lambda d: d['trays'][0]['compartments'][3].update(place_allowed=True),
    lambda d: d['trays'][0]['compartments'][0].update(pick_allowed=True),
    lambda d: d['trays'][0].pop('boundary'),
    lambda d: d.update(status='calibrated'),
    lambda d: d.update(robot_position=[0, 0, 0]),
])
def test_invalid_or_unsafe_config(mutation):
    config = data()
    mutation(config)
    with pytest.raises(ValidationError):
        Workspace.model_validate(config)


def synthetic_region():
    # Arbitrary unit-test geometry, never a lab measurement.
    return dict(frame_id='test_only', units='metres', vertices=[[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]], measurement_record='synthetic_test')


@pytest.mark.parametrize('field', ['valid_pick_region', 'valid_place_region'])
def test_prohibited_region_cannot_be_supplied(field):
    config = data()
    config['trays'][0]['compartments'][2][field] = synthetic_region()
    with pytest.raises(ValidationError, match='Prohibited'):
        Workspace.model_validate(config)


def test_supplied_geometry_does_not_enable_candidate():
    config = data()
    tray = config['trays'][0]
    tray['boundary'] = synthetic_region()
    compartment = tray['compartments'][0]
    for field in ['boundary', 'valid_pick_region', 'valid_place_region']:
        compartment[field] = synthetic_region()
    workspace = Workspace.model_validate(config)
    for action in ['pick', 'place']:
        with pytest.raises(TargetRejected, match='Preparation only'):
            require_valid_target(workspace, tray['id'], compartment['id'], action)


@pytest.mark.parametrize('tray,compartment,action', [
    ('Automatic Pick 1', 'left_1', 'pick'),
    ('automatic_pick_1', 'automatic_pick_2/left_1', 'place'),
    ('automatic_pick_1', 'automatic_pick_1/left_1', 'move'),
])
def test_no_fuzzy_matching_or_unknown_actions(tray, compartment, action):
    with pytest.raises(TargetRejected):
        require_valid_target(load_workspace(), tray, compartment, action)


@pytest.mark.parametrize('vertices', [[], [[0., 0.]] * 3, [[0., 0., 0.]] * 3,
    [[float('nan'), 0., 0.], [1., 0., 0.], [0., 1., 0.]]])
def test_invalid_region(vertices):
    with pytest.raises(ValidationError):
        Region.model_validate({**synthetic_region(), 'vertices': vertices})


def test_missing_file_and_fields_fail(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_workspace(tmp_path / 'missing.json')
    config = data()
    del config['measurements']
    with pytest.raises(ValidationError):
        Workspace.model_validate(config)


def test_mutated_nested_collection_is_revalidated():
    workspace = load_workspace()
    workspace.trays[0].compartments.clear()
    with pytest.raises(ValidationError):
        require_valid_target(workspace, 'automatic_pick_1', 'automatic_pick_1/left_1', 'pick')
