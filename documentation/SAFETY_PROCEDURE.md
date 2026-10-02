# Emergency Stop and Pre-Execution Safety Procedure

**Project:** P54 — Embodied Multimodal LLM for Industrial Task Planning
**Applies to:** every run that moves a physical arm
**Owner:** Kaveesha Dharmadasa (S6-9)
**Status:** draft for team agreement. Two things must be settled before the
first physical run: the reach figure in section 2, and whether the lab's own
rules say something different from section 4. The lab's rules win.

---

## 1. Why this document exists

Up to Sprint 5 every run was in simulation, where a bad coordinate costs a
restart. From Sprint 6 the same pipeline drives a real arm, where the same bad
coordinate can hit the table, the camera mount, or a person.

Two problems made that unsafe to attempt as the code stood.

The first was timing. The only boundary check in the execution path lived inside
`move_to()` on each robot class, and `Executor` sends commands one at a time and
stops at the first failure. A plan whose fourth step was unreachable therefore
ran steps one to three first: locate, move, close the gripper. The failure then
left the arm holding a block somewhere over the table with a person having to
decide what to do about it.

The second was worse. `MockRobot.move_to_object()` set the arm position directly
and checked nothing, and the planner tags every `MOVE` command with an object
name as well as a coordinate, so `Executor` routes the move to that method. The
check in `move_to()` was unreachable for every move a plan actually contains.

Both are fixed. The limits are now checked once, over the whole plan, before the
first command is sent.

---

## 2. Workspace limits

One definition, in `task_planner/safety.py`, read from
`simulation_backend/scene_config.yaml`:

| Limit | Value | Where it comes from |
|---|---|---|
| X | −0.98 m to +0.98 m | table `width_m` 2.0 m, less a 20 mm wall margin |
| Y | −0.73 m to +0.73 m | table `depth_m` 1.5 m, less a 20 mm wall margin |
| Z | 0.00 m to 0.60 m | table surface up to the transit ceiling |
| Reach | 0.80 m from the base | KUKA LBR iiwa 7 **R800** — the designation is the reach |
| Base keep-out | 0.18 m radius | the arm cannot fold into its own base column |

Before Sprint 6 there were four different sets of numbers in the code:
`MockRobot` used `0 ≤ x,y ≤ 10` m, `RobotBase` used ±2.0 m with z down to
−0.5 m, `Kuka_IIWA` used |y| ≤ 0.85 m, and `Franka_panda` used |y| ≤ 0.90 m —
against a table that ends at 0.75 m. Three of the four permitted the arm to
reach past the table edge and into a perimeter wall.

**Two numbers to confirm on hardware before the first physical run.**

The 0.80 m reach is a datasheet figure for the arm the simulation models. It is
not measured, and it does not account for the end effector. Whatever gripper is
fitted adds length at the wrist and will change the usable figure. Confirm the
model plate on the arm in the lab and measure the end effector, then update
`reach_m` in `WorkspaceLimits`.

The margins are thin where it matters. Measured from the base, the two trays sit
at 0.791 m and the workstation at exactly 0.800 m:

| Object | Position (m) | Radius from base | Margin to 0.80 m reach |
|---|---|---|---|
| green block | (+0.35, +0.12) | 0.370 m | +430 mm |
| blue block | (+0.25, +0.35) | 0.430 m | +370 mm |
| yellow block | (+0.25, −0.35) | 0.430 m | +370 mm |
| red block | (+0.45, −0.20) | 0.492 m | +308 mm |
| left tray | (+0.65, +0.45) | 0.791 m | **+9 mm** |
| right tray | (+0.65, −0.45) | 0.791 m | **+9 mm** |
| workstation | (+0.80, 0.00) | 0.800 m | **0 mm** |

Nine millimetres is not a margin on physical hardware. If the measured reach
comes in below the datasheet figure by any amount, both trays and the
workstation move out of range and the scene layout has to change. **Measure the
reach before the cell is laid out, not after.**

---

## 3. What the software does

**Before any motion.** `Executor.execute()` runs `validate_plan()` over every
target position in the plan. If anything is outside the limits the plan is
refused whole, the failure names the step, the coordinate and the limit that was
broken, and no command is sent. `ExecutionResult.blocked_by_safety` is True and
`step_results` is empty, so there is no ambiguity about whether the arm moved.

**During a plan.** If an `EmergencyStop` is supplied, `Executor` checks it before
every command. A stop request halts the plan at the next command boundary, so a
motion already under way completes rather than being cut off part-way. Completed
steps stay completed and are reported.

**How to raise a software stop.**

| From | Action |
|---|---|
| the interactive prompt, between plans | type `stop`. `resume` clears it |
| the terminal, while a plan is running | Ctrl-C once. A second Ctrl-C kills the process outright |
| code | `estop.trigger("reason")` on the shared `EmergencyStop` |

The Ctrl-C handler is installed around plan execution and removed afterwards, so
Ctrl-C at the prompt still quits the program as it always did. Two tests in
`tests/test_safety.py` assert both halves of that, because a procedure that
promises a behaviour nobody wired up is worse than one that promises nothing.

`SAFETY_CHECK=off` disables the pre-execution check. It exists only for
comparing behaviour against the pre-Sprint-6 pipeline and logs a warning every
time it is used. **Never run a physical arm with it set.**

---

## 4. What the software does not do

The software stop needs the Python process to still be running and the
controller to still be accepting commands. Neither holds in the cases where a
stop matters most: a wedged process, a dead network link, a controller fault, an
object in a place nobody expected. It also cannot stop a motion that has already
been commanded — it stops the *next* one.

**The hardware emergency stop on the robot cell is the primary measure. Use it
first, every time. The software stop is for an orderly halt when nothing is
wrong yet.**

### Before any physical run

1. Know where the hardware emergency stop is and that you can reach it from
   where you are standing. Whoever is at the keyboard must be able to hit it
   without moving their feet.
2. Two people present. One at the keyboard, one clear of the cell with a hand
   near the stop.
3. Run the plan in simulation first. The pre-execution check that passes in
   simulation is the same check, with the same numbers, that runs on hardware.
4. Workspace clear of hands, tools, cables and anything not in the scene
   configuration.
5. Speed limited for the first runs of any new instruction.

### If something goes wrong

1. **Hardware emergency stop.** Do not try the software stop first and do not
   wait to see what happens next.
2. Do not reach into the cell. Not to catch a falling block, not to move
   anything out of the way.
3. Leave the arm where it stopped, and leave the terminal output on screen.
4. Tell a supervisor or lab technician before anything is touched or reset.
5. Write down the instruction, the plan and what happened, while it is fresh.
6. Clear the fault and release the stop only once a supervisor agrees it is safe.
   Releasing an emergency stop can re-enable motion.

### Known standards

The relevant published standards are ISO 10218-1 and ISO 10218-2 for industrial
robots and robot cells, and ISO/TS 15066 for collaborative operation. Neither
this document nor this project claims compliance with them, and nobody on the
team has assessed the cell against them.

**Swinburne's own lab rules and the lab technician's instructions take
precedence over everything in this document.** Where they differ, follow them,
and tell the team so this file can be corrected.

---

## 5. Evidence

| What | Where |
|---|---|
| Pre-execution check and emergency stop demonstrated | `documentation/sprint6_safety_evidence.txt` |
| Tests, including every rejection case | `tests/test_safety.py`, 46 tests |
| Guard implementation | `task_planner/safety.py` |
| Pre-flight gate and stop polling | `simulation_backend/executor.py` |

Reproduce with:

```bash
python helper_scripts/demo_safety.py
pytest tests/test_safety.py -v
```
