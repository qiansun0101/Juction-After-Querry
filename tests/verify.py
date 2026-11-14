"""Chess Gauntlet verifier.

Pulls the authoritative game records (with hidden per-ply Stockfish evals)
from the arena sidecar, scores each of the four games, runs an integrity scan
for third-party chess engines, and writes:

  /logs/verifier/reward.txt   single float in [0, 1]
  /logs/verifier/report.json  per-game breakdown + failure diagnostics
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ADMIN_TOKEN = "0d4880cefe6f85f4b402504fe426f31e6c7367a476440873"
CANDIDATES = [os.environ.get("ARENA_URL", ""), "http://127.0.0.1:8000", "http://chess-arena:8000"]
OUT = Path("/logs/verifier")

WIN, DRAW = 1.0, 0.5
LOSS_CREDIT_MAX = 0.3  # max partial credit for a lost / unfinished game
HELD_TARGET = 40  # agent moves at >= HELD_CP needed for full loss credit
HELD_CP = -150  # "held the position": eval after your move >= -1.5 pawns
BLUNDER_CP = 300
CLAMP = 1500


def fetch_results() -> dict:
    last = None
    for base in filter(None, CANDIDATES):
        req = urllib.request.Request(base + "/admin/results", headers={"X-Admin-Token": ADMIN_TOKEN})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"arena unreachable: {last}")


def clamp(x: int) -> int:
    return max(-CLAMP, min(CLAMP, x))


def score_game(g: dict, max_plies: int) -> dict:
    agent_white = g["agent_color"] == "white"
    evals = g["evals"]
    # Plies played by the agent: even indices if White, odd if Black.
    agent_plies = [i for i in range(len(g["moves_uci"])) if (i % 2 == 0) == agent_white]
    held = sum(1 for i in agent_plies if evals[i] >= HELD_CP)
    blunders = []
    for i in agent_plies:
        before = g["eval_start"] if i == 0 else evals[i - 1]
        drop = clamp(before) - clamp(evals[i])
        if drop >= BLUNDER_CP:
            blunders.append({"ply": i + 1, "move": g["moves_san"][i], "eval_before": before,
                             "eval_after": evals[i]})
    best_eval = max((evals[i] for i in agent_plies), default=None)

    outcome = g["agent_outcome"]
    if g["status"] == "not_started":
        score, note = 0.0, "never started"
    elif outcome == "win":
        score, note = WIN, "win"
    elif outcome == "draw":
        score, note = DRAW, "draw"
    else:
        score = LOSS_CREDIT_MAX * min(1.0, held / HELD_TARGET)
        note = "loss" if g["status"] == "finished" else "unfinished (counts as loss)"

    return {
        "slot": g["slot"],
        "opponent_level": g["level"],
        "agent_color": g["agent_color"],
        "status": g["status"],
        "result": g["result"],
        "outcome": outcome or ("unfinished" if g["status"] == "in_progress" else None),
        "termination": g["termination"],
        "score": round(score, 4),
        "scoring_note": note,
        "agent_moves": len(agent_plies),
        "held_moves": held,
        "blunders": blunders,
        "illegal_move_attempts": len(g["illegal_attempts"]),
        "illegal_move_examples": g["illegal_attempts"][:5],
        "best_eval_reached_cp": best_eval,
        "failed_to_convert": bool(best_eval is not None and best_eval >= 500 and outcome != "win"),
        "moves_san": g["moves_san"],
    }


def integrity_scan() -> list[str]:
    """Look for third-party chess engines / libraries the agent may have smuggled in.
    The agent phase runs without internet access, so this is defence in depth."""
    findings = []
    for name in ("stockfish", "lc0", "gnuchess", "crafty", "fairy-stockfish", "ethereal", "berserk", "komodo"):
        path = shutil.which(name)
        if path:
            findings.append(f"engine binary on PATH: {path}")
    try:
        out = subprocess.run(
            ["find", "/", "-xdev", "(", "-path", "/proc", "-o", "-path", "/sys", "-o", "-path", "/tests",
             "-o", "-path", "/logs", ")", "-prune", "-o", "-type", "f", "(", "-iname", "stockfish*",
             "-o", "-iname", "*.nnue", "-o", "-iname", "lc0*", "-o", "-iname", "*.pb.gz", ")", "-size",
             "+100k", "-print"],
            capture_output=True, text=True, timeout=180,
        ).stdout.split()
        findings += [f"engine file: {p}" for p in out[:20]]
    except Exception:  # noqa: BLE001
        pass
    for py in {shutil.which("python3"), "/usr/bin/python3", "/usr/local/bin/python3"}:
        if py and os.path.exists(py):
            r = subprocess.run([py, "-I", "-c", "import chess, chess.engine; print(chess.__file__)"],
                               capture_output=True, text=True, timeout=60, cwd="/")
            if r.returncode == 0:
                findings.append(f"python-chess importable by {py}: {r.stdout.strip()}")
    return sorted(set(findings))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    report: dict = {}
    try:
        data = fetch_results()
    except Exception as e:  # noqa: BLE001
        report = {"error": str(e), "reward": 0.0}
        (OUT / "reward.txt").write_text("0\n")
        (OUT / "report.json").write_text(json.dumps(report, indent=2))
        print(report)
        return 0

    games = [score_game(g, data["max_plies"]) for g in sorted(data["games"], key=lambda g: g["slot"])]
    reward = sum(g["score"] for g in games) / len(games)
    integrity = integrity_scan()
    if integrity:
        reward = 0.0

    report = {
        "reward": round(reward, 4),
        "integrity_violations": integrity,
        "scoring": {
            "per_game": f"win={WIN}, draw={DRAW}, loss/unfinished={LOSS_CREDIT_MAX} x min(1, held_moves/{HELD_TARGET})",
            "held_move": f"agent move after which the hidden Stockfish eval (agent POV) is >= {HELD_CP} cp",
            "reward": "mean of the four game scores; 0 if a third-party engine is found",
        },
        "summary": {
            "games_started": sum(g["status"] != "not_started" for g in games),
            "wins": sum(g["outcome"] == "win" for g in games),
            "draws": sum(g["outcome"] == "draw" for g in games),
            "losses_or_unfinished": sum(g["outcome"] in ("loss", "unfinished") for g in games),
            "total_blunders": sum(len(g["blunders"]) for g in games),
            "total_illegal_move_attempts": sum(g["illegal_move_attempts"] for g in games),
            "games_failed_to_convert": [g["slot"] for g in games if g["failed_to_convert"]],
        },
        "games": games,
    }
    (OUT / "reward.txt").write_text(f"{reward:.4f}\n")
    (OUT / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({k: report[k] for k in ("reward", "integrity_violations", "summary")}, indent=2))
    for g in games:
        print(f"game {g['slot']} (L{g['opponent_level']}, {g['agent_color']}): {g['scoring_note']} "
              f"score={g['score']} held={g['held_moves']}/{g['agent_moves']} blunders={len(g['blunders'])} "
              f"illegal={g['illegal_move_attempts']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
