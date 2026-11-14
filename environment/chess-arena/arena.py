"""Chess Gauntlet arena: authoritative game state + deterministic opponents.

This module runs ONLY inside the `chess-arena` sidecar container. The agent
never sees this file, the Stockfish binary, or the per-move evaluations that
are recorded for the verifier.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

import chess
import chess.engine

STOCKFISH_PATH = os.environ.get("STOCKFISH_PATH", "/usr/games/stockfish")
STATE_PATH = Path(os.environ.get("ARENA_STATE_PATH", "/data/arena_state.json"))
SEED = os.environ.get("ARENA_SEED", "gauntlet-2026")
MAX_PLIES = int(os.environ.get("ARENA_MAX_PLIES", "240"))
# Nodes used for the hidden evaluation that the verifier consumes.
EVAL_NODES = int(os.environ.get("ARENA_EVAL_NODES", "150000"))
MATE_CP = 10000

# ---------------------------------------------------------------------------
# Opponent ladder. Every opponent is Stockfish searching a fixed number of
# nodes (deterministic: Threads=1, hash cleared before every search) and then
# choosing among its top-`multipv` candidates with a seeded softmax, so the
# same agent moves always produce the same opponent replies.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Level:
    name: str
    nodes: int
    multipv: int
    temperature_cp: float  # softmax temperature over candidate scores
    random_move_p: float  # chance of a uniformly random legal move


LEVELS: dict[int, Level] = {
    1: Level("Rookie", nodes=300, multipv=10, temperature_cp=250.0, random_move_p=0.25),
    2: Level("Clubber", nodes=1_000, multipv=8, temperature_cp=120.0, random_move_p=0.12),
    3: Level("Expert", nodes=3_000, multipv=5, temperature_cp=60.0, random_move_p=0.05),
    4: Level("Master", nodes=15_000, multipv=3, temperature_cp=25.0, random_move_p=0.0),
}

SLOTS: list[dict] = [
    {"slot": 1, "level": 1, "agent_color": "white"},
    {"slot": 2, "level": 2, "agent_color": "black"},
    {"slot": 3, "level": 3, "agent_color": "white"},
    {"slot": 4, "level": 4, "agent_color": "black"},
]


class ArenaError(Exception):
    """An error whose message is safe and useful to show to the agent."""


def _score_cp(score: chess.engine.PovScore, pov: chess.Color) -> int:
    return int(score.pov(pov).score(mate_score=MATE_CP))


@dataclass
class Game:
    slot: int
    level: int
    agent_color: str
    status: str = "not_started"  # not_started | in_progress | finished
    moves_uci: list[str] = field(default_factory=list)
    moves_san: list[str] = field(default_factory=list)
    # evals[i] = eval (centipawns, from the AGENT's point of view) of the
    # position after ply i+1. evals_start = eval of the initial position.
    evals: list[int] = field(default_factory=list)
    eval_start: int | None = None
    illegal_attempts: list[dict] = field(default_factory=list)
    result: str | None = None  # "1-0" | "0-1" | "1/2-1/2"
    agent_outcome: str | None = None  # win | draw | loss
    termination: str | None = None
    started_at: float | None = None
    finished_at: float | None = None

    def board(self) -> chess.Board:
        b = chess.Board()
        for m in self.moves_uci:
            b.push_uci(m)
        return b

    @property
    def agent_is_white(self) -> bool:
        return self.agent_color == "white"


class Arena:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._engine: chess.engine.SimpleEngine | None = None
        self.games: dict[int, Game] = {}
        self._load()

    # -- persistence -------------------------------------------------------
    def _load(self) -> None:
        if STATE_PATH.exists():
            data = json.loads(STATE_PATH.read_text())
            self.games = {int(k): Game(**v) for k, v in data["games"].items()}
        else:
            self.games = {
                s["slot"]: Game(slot=s["slot"], level=s["level"], agent_color=s["agent_color"])
                for s in SLOTS
            }
            self._save()

    def _save(self) -> None:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps({"games": {k: asdict(g) for k, g in self.games.items()}}))
        tmp.replace(STATE_PATH)

    # -- engine --------------------------------------------------------------
    def _eng(self) -> chess.engine.SimpleEngine:
        if self._engine is None:
            self._engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
            self._engine.configure({"Threads": 1, "Hash": 16})
        return self._engine

    def _analyse(self, board: chess.Board, nodes: int, multipv: int = 1) -> list[dict]:
        # A fresh `game` object makes python-chess send `ucinewgame`, clearing
        # the hash so results do not depend on earlier searches.
        try:
            infos = self._eng().analyse(
                board, chess.engine.Limit(nodes=nodes), multipv=multipv, game=uuid.uuid4()
            )
        except chess.engine.EngineTerminatedError:
            self._engine = None
            infos = self._eng().analyse(
                board, chess.engine.Limit(nodes=nodes), multipv=multipv, game=uuid.uuid4()
            )
        return infos

    def _eval_agent_pov(self, game: Game, board: chess.Board) -> int:
        agent = chess.WHITE if game.agent_is_white else chess.BLACK
        outcome = board.outcome(claim_draw=True)
        if outcome is not None:
            if outcome.winner is None:
                return 0
            return MATE_CP if outcome.winner == agent else -MATE_CP
        info = self._analyse(board, EVAL_NODES)[0]
        return _score_cp(info["score"], agent)

    def _opponent_move(self, game: Game, board: chess.Board) -> chess.Move:
        level = LEVELS[game.level]
        seed = hashlib.sha256(
            f"{SEED}|{game.slot}|{len(board.move_stack)}|{board.fen()}".encode()
        ).digest()
        rng = random.Random(seed)
        legal = sorted(board.legal_moves, key=lambda m: m.uci())
        if level.random_move_p > 0 and rng.random() < level.random_move_p:
            return rng.choice(legal)
        infos = self._analyse(board, level.nodes, multipv=min(level.multipv, len(legal)))
        cands = [(i["pv"][0], _score_cp(i["score"], board.turn)) for i in infos if i.get("pv")]
        if len(cands) == 1:
            return cands[0][0]
        best = max(s for _, s in cands)
        weights = [math.exp((s - best) / level.temperature_cp) for _, s in cands]
        r = rng.random() * sum(weights)
        for (move, _), w in zip(cands, weights):
            r -= w
            if r <= 0:
                return move
        return cands[0][0]

    # -- game flow -------------------------------------------------------------
    def _get(self, slot: int) -> Game:
        try:
            slot = int(slot)
        except (TypeError, ValueError):
            raise ArenaError(f"slot must be an integer 1-{len(SLOTS)}")
        if slot not in self.games:
            raise ArenaError(f"unknown slot {slot}; valid slots are 1-{len(SLOTS)}")
        return self.games[slot]

    def _push(self, game: Game, board: chess.Board, move: chess.Move) -> None:
        game.moves_san.append(board.san(move))
        game.moves_uci.append(move.uci())
        board.push(move)
        game.evals.append(self._eval_agent_pov(game, board))

    def _check_end(self, game: Game, board: chess.Board) -> bool:
        outcome = board.outcome(claim_draw=True)
        agent = chess.WHITE if game.agent_is_white else chess.BLACK
        if outcome is not None:
            game.result = outcome.result()
            game.termination = outcome.termination.name.lower()
            if outcome.winner is None:
                game.agent_outcome = "draw"
            else:
                game.agent_outcome = "win" if outcome.winner == agent else "loss"
        elif len(board.move_stack) >= MAX_PLIES:
            game.result = "0-1" if game.agent_is_white else "1-0"
            game.termination = "move_limit_reached"
            game.agent_outcome = "loss"
        else:
            return False
        game.status = "finished"
        game.finished_at = time.time()
        return True

    def start(self, slot: int) -> dict:
        with self._lock:
            game = self._get(slot)
            if game.status != "not_started":
                raise ArenaError(
                    f"game {game.slot} was already started (status: {game.status}); "
                    "each game can be played only once"
                )
            active = [g.slot for g in self.games.values() if g.status == "in_progress"]
            if active:
                raise ArenaError(
                    f"game {active[0]} is still in progress; finish or resign it before "
                    "starting another game (only one game may be active at a time)"
                )
            game.status = "in_progress"
            game.started_at = time.time()
            board = chess.Board()
            game.eval_start = self._eval_agent_pov(game, board)
            if not game.agent_is_white:
                self._push(game, board, self._opponent_move(game, board))
            self._save()
            return self.state(game.slot)

    def move(self, slot: int, move_text: str) -> dict:
        with self._lock:
            game = self._get(slot)
            if game.status != "in_progress":
                raise ArenaError(f"game {game.slot} is not in progress (status: {game.status})")
            board = game.board()
            text = (move_text or "").strip()
            move = None
            for parse in (board.parse_san, board.parse_uci):
                try:
                    move = parse(text)
                    break
                except ValueError:
                    continue
            if move is None or move not in board.legal_moves:
                game.illegal_attempts.append({"ply": len(board.move_stack), "move": text})
                self._save()
                raise ArenaError(
                    f"illegal or unparseable move {text!r} in position {board.fen()}. "
                    "Use SAN (e.g. Nf3, exd5, O-O, e8=Q) or UCI (e.g. g1f3). "
                    "Call get_state to see the legal moves."
                )
            self._push(game, board, move)
            if not self._check_end(game, board):
                self._push(game, board, self._opponent_move(game, board))
                self._check_end(game, board)
            self._save()
            return self.state(game.slot)

    def resign(self, slot: int) -> dict:
        with self._lock:
            game = self._get(slot)
            if game.status != "in_progress":
                raise ArenaError(f"game {game.slot} is not in progress (status: {game.status})")
            game.status = "finished"
            game.result = "0-1" if game.agent_is_white else "1-0"
            game.termination = "resignation"
            game.agent_outcome = "loss"
            game.finished_at = time.time()
            self._save()
            return self.state(game.slot)

    # -- views -----------------------------------------------------------------
    def state(self, slot: int) -> dict:
        with self._lock:
            game = self._get(slot)
            board = game.board()
            hist = []
            for i in range(0, len(game.moves_san), 2):
                pair = " ".join(game.moves_san[i : i + 2])
                hist.append(f"{i // 2 + 1}. {pair}")
            agent_turn = game.status == "in_progress" and (
                (board.turn == chess.WHITE) == game.agent_is_white
            )
            last_opp = None
            if game.moves_san:
                last_ply_white = len(game.moves_san) % 2 == 1
                if last_ply_white != game.agent_is_white:
                    last_opp = game.moves_san[-1]
            return {
                "slot": game.slot,
                "opponent": LEVELS[game.level].name,
                "opponent_level": game.level,
                "your_color": game.agent_color,
                "status": game.status,
                "your_turn": agent_turn,
                "side_to_move": "white" if board.turn == chess.WHITE else "black",
                "fen": board.fen(),
                "board": _ascii(board),
                "move_history": " ".join(hist),
                "last_opponent_move": last_opp,
                "legal_moves": sorted(board.san(m) for m in board.legal_moves)
                if game.status == "in_progress"
                else [],
                "in_check": board.is_check(),
                "plies_played": len(game.moves_uci),
                "plies_until_move_limit": max(0, MAX_PLIES - len(game.moves_uci)),
                "result": game.result,
                "your_outcome": game.agent_outcome,
                "termination": game.termination,
            }

    def overview(self) -> dict:
        with self._lock:
            return {
                "games": [
                    {
                        "slot": g.slot,
                        "opponent": LEVELS[g.level].name,
                        "opponent_level": g.level,
                        "your_color": g.agent_color,
                        "status": g.status,
                        "result": g.result,
                        "your_outcome": g.agent_outcome,
                    }
                    for g in self.games.values()
                ],
                "rules": {
                    "one_attempt_per_game": True,
                    "one_active_game_at_a_time": True,
                    "move_limit_plies": MAX_PLIES,
                },
            }

    def admin_results(self) -> dict:
        with self._lock:
            return {
                "seed": SEED,
                "max_plies": MAX_PLIES,
                "eval_nodes": EVAL_NODES,
                "levels": {k: asdict(v) for k, v in LEVELS.items()},
                "games": [asdict(g) for g in self.games.values()],
            }


def _ascii(board: chess.Board) -> str:
    rows = []
    for rank in range(7, -1, -1):
        cells = []
        for file in range(8):
            p = board.piece_at(chess.square(file, rank))
            cells.append(p.symbol() if p else ".")
        rows.append(f"{rank + 1} | " + " ".join(cells))
    rows.append("    ---------------")
    rows.append("    a b c d e f g h")
    rows.append("(uppercase = White, lowercase = Black)")
    return "\n".join(rows)
