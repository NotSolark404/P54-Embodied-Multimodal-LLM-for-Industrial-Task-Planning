# Deployment

Three images are built from one `Dockerfile`:

| Image | Target | What it is |
|---|---|---|
| `p54-sim` | `sim` | Simulation only (PyBullet, mock robot) |
| `p54-robot` | `robot` | Physical UR5 + OnRobot RG2 over URScript |
| `p54-full` | `full` | Both; choose with `ROBOT_BACKEND=mock` or `urscript` |

The code is built into each image. All three share the same requirements today, and the
difference is the default robot backend.

## First time

```bash
cp .env.example .env            # fill in your settings
docker compose --profile sim up -d --build        # or: robot, full
docker compose exec ollama ollama pull qwen2.5:7b # one-time model download
```

Start one profile at a time. To make a profile the default, add `COMPOSE_PROFILES=robot`
to `.env`, then plain `docker compose up -d` starts it.

## Run an instruction

```bash
docker compose exec p54-sim   python3 -B main.py "pick up the red block and place it in the left tray"
docker compose exec p54-robot python3 -B main.py "pick up the grey tray from bottom tray slot 2 and place it in top tray slot 1"
```

The simulation scene has coloured blocks and two trays. The robot scene has the grey tray and the
six tray slots (bottom tray slot 1 to 3, top tray slot 1 to 3).

## Full image

`p54-full` follows `ROBOT_BACKEND`, and a value set in the terminal beats `.env`:

```bash
ROBOT_BACKEND=mock     docker compose --profile full up -d   # simulation
ROBOT_BACKEND=urscript docker compose --profile full up -d   # real arm
```

## Physical robot checklist

- `.env` has `UR5_ROBOT_IP`, and this computer can reach the robot on the lab network.
- `grip_close.urp` (RG2, 60 mm, 40 N) and `grip_open.urp` (RG2, 67 mm, 40 N) are saved on the pendant.
- Someone stands at the pendant emergency stop, and the area around the arm is clear.
- Speed settings (`UR5_MOVE_SPEED`, `UR5_TRANSIT_SPEED`, `UR5_GRIPPER_WAIT`) are in `.env`.
- Slot poses live in `simulation_backend/robots/ur5_script_robot.py`. If the table or trays move,
  re-record them with `record_pose.py` and rebuild the image.
- The tray position is remembered in `/data/tray_state.json`. If the startup line
  `grey tray believed to be at ...` is wrong, clear it:
  `docker compose exec p54-robot rm -f /data/tray_state.json`.

## Testing without the robot

Add `-e UR5_DRY_RUN=1` to print the robot commands without moving anything:

```bash
docker compose exec -e UR5_DRY_RUN=1 p54-robot python3 -B main.py "move the grey tray to top tray slot 1"
```

Dry runs also update the remembered tray position, so clear it before a real run.

## Stop

```bash
docker compose --profile robot down --remove-orphans
```