# Branch Closeout

**Ticket:** S6-10 — repository cleanup
**Owner:** Kaveesha Dharmadasa
**Surveyed:** 2 October 2026, against `main` at `b9a64a9`

Sprint 5's retrospective raised unmerged branches and nothing happened after it.
This is the survey, with a recommendation per branch. **Only the owner of each
branch should act on their own row** — deleting someone else's branch on a
recommendation they have not read is how work gets lost, and this repository has
already lost a file that way (see the last section).

`main` has eleven other remote branches.

---

## 1. Already fully merged — safe to delete, nothing is lost

Each of these has zero commits that `main` does not already contain. Deleting
them removes nothing.

| Branch | Last commit | Behind main |
|---|---|---|
| `Kaveesha_Sprint_5_MultiAction` | 8 Sep 2026 — Kaveesha | 12 |
| `lakshit_bansal_sprint_2` | 8 May 2026 — Lakshit | 76 |
| `Sprint-3` | 7 Jun 2026 — Ved | 42 |
| `Ved_Sprint_2_1` | 27 Apr 2026 — Ved | 108 |
| `Ved_Sprint_6_2` | 18 Apr 2026 — Ved | 114 |

**`Ved_Sprint_6_2` is worth a second look before anyone relies on the name.** It
is dated 18 April 2026 and sits 114 commits behind `main`, so despite being
called Sprint 6 it predates almost everything. If Sprint 6 work is meant to go
somewhere, it is not here.

Verify before deleting any of them:

```bash
git rev-list --count main..origin/<branch>     # must print 0
```

---

## 2. Still ahead of main — a decision is needed

### `planner-disc-merge` — 2 commits ahead, 0 behind. **Merge or close this sprint.**

Ved, 1 October 2026. Adds disc and slot support to `task_planner/planner.py`
(+278 / −16), and the commit message says it keeps `main`'s spatial tests
passing. Zero commits behind `main`, so it merges cleanly today.

This is the only unmerged branch that touches planner behaviour, which makes it
the one with a real deadline: the longer it sits, the more Sprint 6 work lands on
top of a planner it has not been tested against. **Owner: Ved.**

### `restore-recovered-work` — 3 commits ahead, 0 behind. **Do not merge as it stands.**

Ved, 1 October 2026, after local data loss. 39 files, +8,640 lines, and it
reintroduces a flat layout the project moved away from — `llm_module/`,
`vision_backend/`, `vision_server.py`, `test_sprint2.py` at the repository root —
alongside files that already exist in their current locations. Merging it would
give the project two copies of several modules in two different layouts.

Its own commit messages say what it is for: *"recovered Sprint 5 version saved
aside for manual merge"*. It is a recovery staging area, not a feature branch.
**Owner: Ved.** Take what is genuinely missing from `main`, put it in the current
layout, and close the branch. Keep it until that is done.

### `lakshit_sprint_3` — 3 commits ahead, 68 behind. **Needed for S6-4.**

Lakshit, 29 May – 4 Jun 2026. Carries `simulation_backend/real_robot.py` (323
lines) and a substantially rewritten `main.py` (+478 / −187).

That `real_robot.py` is the only physical-robot driver anybody on the team has
written, and S6-4 is the physical execution ticket. 68 commits behind means the
`main.py` rewrite will conflict heavily with the current one and should not be
merged wholesale. **Owner: Lakshit.** Port `real_robot.py` onto current `main`;
leave the old `main.py` behind. If it lands, check it against
`task_planner/safety.py` first — nothing in that file has been through the
pre-execution check.

### `feature/vision-module_dinith` — 3 commits ahead, 126 behind. **Probably closeable.**

Dinith, 15–16 Apr 2026. Six files at the repository root: `vision_output.py`,
`scene_representation.py`, `spatial_relationships.py` and three JSON outputs.
126 commits behind, and `simulation_backend/vision/` has since superseded all of
it.

**Owner: Dinith.** Confirm nothing here is still wanted — the JSON files may be
useful as early output examples — then close it.

### `Kaveesha` — 3 commits ahead, 64 behind. **Mine. Closing it, with one file lifted out first.**

My own branch, 5 May – 2 Jun 2026. Carries an older `task_planner/planner.py`
(+481 / −179), `task_planner/schema.py`, `tests/test_planner.py`, and
`task_planner/safety.py` — the file Sprint 4 recorded as lost in a planner
rewrite.

That file is the reason S6-9 exists, so I read it before writing the replacement.
It is 32 lines and hardcodes `X ∈ [0.1, 0.8]`, `Y ∈ [−0.4, 0.4]`,
`Z ∈ [0.0, 0.5]`.

**Restoring it verbatim would have broken the project.** Both trays sit at
y = ±0.45, outside `Y ∈ [−0.4, 0.4]`, so every tray placement in the scene would
have been rejected as a boundary violation — and the workstation at x = 0.80 sat
exactly on the X limit with nothing to spare. The ticket says put the guard back;
putting that guard back would have blocked the most common instruction the
pipeline handles.

So S6-9 rebuilds it rather than reverting it: limits read from
`scene_config.yaml` instead of hardcoded, a reach envelope as well as a box, a
check over the whole plan instead of one position at a time, and 44 tests. The
rest of the branch — the old planner and schema — is superseded by `main` and
goes nowhere.

**Closing after Sprint 6 review**, once the comparison above has been through the
report.

### `Sprint_5_Ved` — 2 commits ahead, 17 behind. **One line worth keeping.**

Ved, 12 September 2026. Two files: `full_demo_output.txt` (635 lines of demo
output) and one `.gitignore` line adding `task_log.json`.

The `.gitignore` line is worth having on `main` — `task_log.json` is a generated
run log and is currently tracked, so every run shows up as a modified file. The
demo output belongs in `documentation/` if it is kept at all. **Owner: Ved.**

---

## 3. Summary

| Action | Branches |
|---|---|
| Delete — fully merged | `Kaveesha_Sprint_5_MultiAction`, `lakshit_bansal_sprint_2`, `Sprint-3`, `Ved_Sprint_2_1`, `Ved_Sprint_6_2` |
| Merge this sprint | `planner-disc-merge` |
| Port one file, then close | `lakshit_sprint_3`, `Sprint_5_Ved` |
| Resolve manually, then close | `restore-recovered-work` |
| Close | `Kaveesha`, `feature/vision-module_dinith` |

Five deletions need nothing but a confirmation. The other six need their owner to
spend twenty minutes on them, and `planner-disc-merge` needs it first.

---

## 4. The thing that caused this

`task_planner/safety.py` was deleted during a planner rewrite and nobody noticed
until Sprint 4. The file still existed on a branch nobody was merging, so the
loss was invisible: `main` had no boundary check and no test failed, because the
tests that covered it were on the same unmerged branch.

That is what long-lived branches cost. They do not just delay work, they hide the
absence of it. Worth saying in the retrospective, and worth not repeating in the
final sprint.
