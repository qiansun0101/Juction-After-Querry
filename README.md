# Chess Gauntlet

A Harbor environment in which an agent plays four games of chess against a ladder
of increasingly strong opponents. It has no internet and no chess engine, and it
has to finish all four games within a 2-hour budget.

```
./run.sh oracle                                   # reference solution, no API key
./run.sh openrouter/anthropic/claude-sonnet-4.5   # OpenCode + any model (needs a key in .env)
```

## What the agent has to do

A chess-arena server runs next to the agent. The agent can reach it through
**MCP tools** (`list_games`, `start_game`, `get_state`, `make_move`, `resign`),
through a `chess` CLI, or through a REST API. Every response contains the board,
the FEN, the move history and the full list of legal moves, so the agent always
has everything it needs to play legally.

| Game | Opponent | You play |
|------|----------|----------|
| 1 | Rookie (L1)  | White |
| 2 | Clubber (L2) | Black |
| 3 | Expert (L3)  | White |
| 4 | Master (L4)  | Black |

The rules:
- Each game can be played only once.
- Only one game may be active at a time.
- There are no take-backs.
- A game still unfinished at 240 plies, or when time runs out, counts as a loss.

## Why it's hard

Chess isolates abilities that frontier agents still lack in long tasks:

- **Planning several moves ahead.** Every opponent reply punishes a one-move
  horizon. Typical failures are hanging pieces, missing forks and walking into
  mate.
- **Tracking state over a long horizon.** A game is 60–120 plies. Agents lose
  track of the position, try illegal moves and misremember who is attacking
  what. The verifier logs every illegal attempt.
- **Converting an advantage.** Agents often reach a winning position and then
  fail to deliver mate, stalemate the opponent or allow a draw by repetition.
  The verifier reports this as `failed_to_convert`.
- **Using tools well.** No engine or chess library is installed, and there is
  no internet. The agent may write its own search code, which is legitimate,
  but a correct move generator plus search is non-trivial. The reference
  solution shows that it is possible: a dependency-free engine of about 350
  lines in `solution/engine.py`.
- **Managing limited resources.** One 2-hour budget covers four games. Spending
  too long on game 1 means game 4 is never finished.

The four opponents are Stockfish at different strengths: a fixed node count,
then a seeded pick among the top candidate moves. Given the same agent moves,
the opponent's replies are **fully deterministic**, so runs are reproducible.

### Calibration of the ladder

These are offline matches, 4 games per cell, alternating colours. Cells are
average score per game.

| Player | L1 | L2 | L3 | L4 |
|--------|----|----|----|----|
| Random mover | 0.00 | 0.00 | 0.00 | 0.00 |
| Stockfish limited to 1320 Elo | 1.00 | 1.00 | 0.38 | 0.00 |
| Reference engine (`solution/engine.py`, 2 s/move) | 1.00 | 1.00 | 0.88 | – |

## How it's scored

`tests/verify.py` pulls the authoritative game records from the arena. The agent
cannot edit them, and they include a hidden Stockfish evaluation after every ply.
Each game is scored as follows:

| Outcome | Score |
|---------|-------|
| Win | 1.0 |
| Draw (stalemate, repetition, 50-move rule, insufficient material) | 0.5 |
| Loss / resignation / unfinished | `0.3 × min(1, held_moves / 40)` |
| Never started | 0 |

A **held move** is an agent move after which the hidden evaluation, from the
agent's side, is at least −150 centipawns. Partial credit therefore rewards
keeping a level game against the engine. It cannot be farmed: once an agent has
blundered into a lost position, further moves earn nothing. Even a perfectly
held loss is worth less than a draw.

**Reward = mean of the four game scores**, written to `/logs/verifier/reward.txt`.
`/logs/verifier/report.json` contains the per-game breakdown: blunders (eval
drops of 300 cp or more), illegal-move attempts, best eval reached, failed
conversions and the full move list.

## Reward integrity

| Exploit attempt | Defence |
|-----------------|---------|
| `pip install python-chess` / `apt install stockfish` | Agent phase runs with `network_mode = "no-network"`. Harbor allowlists only the model's inference host. Tested: pypi is unreachable from the container, even via a proxy. |
| Use the opponent's engine | Stockfish lives only in the `chess-arena` sidecar container. The agent has no filesystem or process access to it. |
| Read the hidden evals / forge results | Evals are never returned by the public API. `/admin/results` needs a token that exists only in `environment/docker-compose.yaml` (on the host) and `tests/` (copied in after the agent finishes). |
| Retry a game until a lucky win (deterministic opponent) | Each game can be started once. There are no restarts or take-backs. |
| Relay moves between two games so the engine plays itself | Only one game may be in progress at a time. |
| Do nothing / quit early | Unstarted games score 0. A quick resignation earns at most a few hundredths. |
| Smuggled engine anyway | The verifier scans for engine binaries, NNUE nets and an importable python-chess. Any hit sets the reward to 0. |

## Results

Run logs are in [`runs/`](runs/). Each folder is a full Harbor trial directory
(`result.json`, `trial.log`, `verifier/report.json`, `verifier/reward.txt`).

| Run | Reward | Notes |
|-----|--------|-------|
| Oracle (`solution/`, self-written engine) | **0.6306** | Won L1 and L2, drew L3, lost L4 |
| Do-nothing baseline (`-a nop`) | **0.0000** | |
| Stop-early baseline (3 moves, then resign every game) | **0.0187** | |
| OpenCode + frontier model | _TODO: run_ | `./run.sh <provider/model>` |

## Running it

Requirements: Docker and Harbor (`uv tool install harbor`). The arena is a
docker-compose sidecar, so use the **docker** environment.

```
cp .env.example .env        # then put ONE API key in .env
./run.sh oracle             # reference solution
./run.sh nop                # do-nothing baseline
./run.sh openrouter/anthropic/claude-sonnet-4.5 3   # OpenCode, 3 attempts
```

Or call Harbor directly:

```
harbor run -p . -a opencode -m <provider/model> -e docker
```

Results land in `./jobs/<timestamp>/`.

## Layout

```
instruction.md                 what the agent sees
task.toml                      timeouts, no-network agent phase, MCP server
environment/Dockerfile         agent container (python3, curl, `chess` CLI)
environment/client/chess       CLI client
environment/docker-compose.yaml  adds the chess-arena sidecar
environment/chess-arena/       arena server (MCP + REST), opponents, hidden evals
tests/test.sh, tests/verify.py verifier
solution/                      reference solution: pure-Python engine
runs/                          Harbor run logs
```
