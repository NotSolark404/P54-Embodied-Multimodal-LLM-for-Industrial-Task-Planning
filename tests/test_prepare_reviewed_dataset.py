"""Synthetic tests for explicit manual-revision export; no model loaded."""
import hashlib
import json

import cv2
import numpy as np
import pytest
import yaml

from fine_tuning.yolov8_real_workspace.prepare_reviewed_dataset import prepare
from fine_tuning.yolov8_real_workspace.validate_dataset import validate_groups


@pytest.fixture
def selected(tmp_path):
    source = tmp_path/'source.png'
    cv2.imwrite(str(source), np.zeros((20, 20, 3), np.uint8))
    checksum = hashlib.sha256(source.read_bytes()).hexdigest()
    work = tmp_path/'work'
    draft = work/'drafts/source/revision.json'
    draft.parent.mkdir(parents=True)
    (work/'inventory.json').write_text(json.dumps([dict(source=str(source),sha256=checksum,group='one_scene')]))
    draft.write_text(json.dumps(dict(source_sha256=checksum,names=['tray','component'],
        boxes=[dict(class_id=1,box=[0,0,20,20])])))
    draft.with_suffix('.txt').write_text('1 0.50000000 0.50000000 1.00000000 1.00000000\n')
    review=work/'review.json'
    review.write_text(json.dumps([dict(revision='drafts/source/revision.json',reviewed=True,reviewer='TEST')]))
    data=tmp_path/'dataset/data.yaml'
    data.parent.mkdir()
    data.write_text(yaml.safe_dump(dict(classes_confirmed=True,names=['tray','component'],annotations_confirmed=False)))
    return review,data,work,source,draft


def test_export_preserves_sources_and_no_split(selected):
    review,data,work,source,draft=selected
    before=(source.read_bytes(),draft.read_bytes())
    assert prepare(review,data,work)==1
    assert (source.read_bytes(),draft.read_bytes())==before
    assert (data.parent/'images/train/source.png').read_bytes()==before[0]
    assert not list((data.parent/'images/val').iterdir())
    assert not yaml.safe_load(data.read_text())['annotations_confirmed']
    validate_groups(data.parent,{'images/train/source.png':data.parent/'images/train/source.png'})
    with pytest.raises(ValueError,match='overwrite'):
        prepare(review,data,work)


@pytest.mark.parametrize('failure',['hash','labels','review'])
def test_invalid_selection_rejected_before_export(selected,failure):
    review,data,work,source,draft=selected
    if failure=='hash':
        source.write_bytes(b'changed')
    elif failure=='labels':
        draft.with_suffix('.txt').write_text('0 0.5 0.5 1 1\n')
    else:
        records=json.loads(review.read_text());records[0]['reviewed']=False
        review.write_text(json.dumps(records))
    with pytest.raises(ValueError):
        prepare(review,data,work)
    assert not (data.parent/'images').exists()
