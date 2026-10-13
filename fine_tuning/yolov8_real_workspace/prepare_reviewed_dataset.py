"""Copy explicitly reviewed manual revisions into train only; never train a model."""
import argparse
import hashlib
import json
from pathlib import Path

import cv2
import yaml

from .annotation import DATA, WORK, yolo_row
from .validate_dataset import class_names, parse_labels


def prepare(review_path, data=DATA, work=WORK):
    data, work = Path(data), Path(work)
    root = data.parent
    config = yaml.safe_load(data.read_text())
    names = class_names(config)
    if config.get('annotations_confirmed') is not False:
        raise ValueError('Preparation requires annotations_confirmed: false; final approval is separate')
    inventory = {Path(r['source']).stem: r for r in json.loads((work/'inventory.json').read_text())}
    reviews = json.loads(Path(review_path).read_text())
    if not isinstance(reviews, list) or not reviews:
        raise ValueError('Provide explicit reviewed revisions')
    planned, groups, seen = [], {}, set()
    for review in reviews:
        if review.get('reviewed') is not True or not review.get('reviewer'):
            raise ValueError('Each selected revision needs a recorded reviewer')
        revision = (work / review['revision']).resolve()
        if not revision.is_relative_to((work/'drafts').resolve()):
            raise ValueError('Revision must be inside manual drafts')
        record = inventory[revision.parent.name]
        source = Path(record['source'])
        image_bytes = source.read_bytes()
        checksum = hashlib.sha256(image_bytes).hexdigest()
        payload = json.loads(revision.read_text())
        if checksum != record['sha256'] or checksum != payload['source_sha256']:
            raise ValueError('Source checksum mismatch')
        if payload['names'] != names:
            raise ValueError('Draft class map differs from confirmed classes')
        image = cv2.imread(str(source))
        if image is None:
            raise ValueError('Unreadable source')
        rows = [yolo_row(b['class_id'], b['box'], image.shape[1], image.shape[0]) for b in payload['boxes']]
        labels = '\n'.join(rows) + ('\n' if rows else '')
        parse_labels(labels, len(names))
        if revision.with_suffix('.txt').read_text() != labels:
            raise ValueError('Draft JSON and TXT disagree')
        relative = f"images/train/{source.name}"
        if relative in seen:
            raise ValueError('Duplicate selected source')
        seen.add(relative)
        targets = [(root/relative, image_bytes),
                   (root/'labels/train'/f'{source.stem}.txt', labels.encode())]
        planned.extend(targets)
        groups[relative] = dict(group=record['group'], sha256=checksum)
    planned.extend([(root/'split_groups.json', (json.dumps(groups, indent=2)+'\n').encode()),
                    (root/'annotation_review.json', (json.dumps(reviews, indent=2)+'\n').encode())])
    if any(path.exists() for path, _ in planned):
        raise ValueError('Refusing to overwrite existing dataset files')
    # This deliberately stages a single split; it cannot randomly split a burst.
    for split in ('train', 'val', 'test'):
        for kind in ('images', 'labels'):
            (root/kind/split).mkdir(parents=True, exist_ok=True)
    for path, content in planned:
        with path.open('xb') as handle:
            handle.write(content)
    return len(reviews)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('review', type=Path)
    args = parser.parse_args()
    print(f'Staged {prepare(args.review)} images in train. No training started.')
