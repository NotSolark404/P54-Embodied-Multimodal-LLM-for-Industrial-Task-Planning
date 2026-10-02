# Release Checklist — v1.0

**Ticket:** S6-10 — tagged release
**Owner:** Kaveesha Dharmadasa
**Status:** prepared, not cut. The tag waits on work that is not mine.

A release tag is a claim that what it points at works. Cutting one now would
point it at a `main` that has no real camera, no calibration and no physical
robot path, which is most of what Sprint 6 is for. So this is the checklist and
the commands, ready to run on the day, rather than a tag on an unfinished tree.

---

## Blocked on

| Ticket | Owner | Must be merged first |
|---|---|---|
| S6-1, S6-2 | Dinith | real camera capture, a detector that does not read positions out of the simulator, calibration |
| S6-4, S6-5 | Lakshit | physical robot execution, first lab run of `docker-compose.lab.yml` |
| S6-6, S6-7 | Ved | planner work, and `planner-disc-merge` merged or closed |
| S6-8 | Minh | evaluation numbers the release notes will quote |

---

## Before tagging

- [ ] Every Sprint 6 branch above merged to `main`, and `documentation/BRANCH_CLOSEOUT.md` worked through.
- [ ] `pytest -m "not integration"` green on `main`. Record the count — any new failure is either fixed or written down with a reason, not skipped.
- [ ] `pytest -m integration` run once with a real key, by whoever has budget for it.
- [ ] Fresh clone, documented setup followed exactly, tests run. The same check as `documentation/sprint6_fresh_clone_evidence.txt`, on `main`.
- [ ] README's Physical Robot Operation section rewritten to describe what the hardware actually did, not what is planned. Every "not implemented" either gone or still true.
- [ ] `documentation/SAFETY_PROCEDURE.md` agreed by the team, and the measured arm reach substituted for the datasheet figure.
- [ ] No key, token or `.env` anywhere in the tree or the history: `git log -p | grep -iE "sk-|api_key *=" | grep -v example`
- [ ] Final report submitted. The tag should be the tree the report describes.

## Cutting it

```bash
git checkout main && git pull
git tag -a v1.0 -m "COS40005 P54 — final submission"
git push origin v1.0
gh release create v1.0 --title "P54 v1.0 — Final Submission" --notes-file documentation/RELEASE_NOTES.md
```

`RELEASE_NOTES.md` does not exist yet. It should be written from the final report
rather than invented separately, so the two cannot disagree, and it needs the
limitations as plainly as the results: what ran on hardware, what did not, and
the accuracy figures with the conditions they were measured under.

## After

- [ ] Tag visible on GitHub, and a fresh clone of the tag passes the tests.
- [ ] Tag link in the final report and in the Sprint 6 report.
