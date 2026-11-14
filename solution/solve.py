"""Reference solution: play all four gauntlet games with a self-written engine."""

import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E  # noqa: E402

SECONDS_PER_MOVE = float(os.environ.get("SOLVE_SECONDS_PER_MOVE", "4"))
CANDIDATES = [os.environ.get("ARENA_URL", ""), "http://127.0.0.1:8000", "http://chess-arena:8000"]


def _req(base, path, body=None):
    data = json.dumps(body).encode() if body is not None else (b"" if path.endswith(("start", "resign")) else None)
    req = urllib.request.Request(base + path, data=data, method="POST" if data is not None else "GET",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())


def find_base():
    for base in filter(None, CANDIDATES):
        try:
            _req(base, "/api/games")
            return base
        except Exception:
            continue
    raise SystemExit("arena not reachable")


def play(base, slot):
    st = _req(base, f"/api/games/{slot}/start")
    if "error" in st:
        print("start failed:", st["error"])
        return
    searcher = E.Searcher()
    seen = []
    while st["status"] == "in_progress":
        pos, white = E.from_fen(st["fen"])
        seen.append(pos.board)
        m = searcher.best_move(pos, SECONDS_PER_MOVE, history=set(seen[:-1]))
        uci = E.move_to_uci(m, white)
        nxt = _req(base, f"/api/games/{slot}/move", {"move": uci})
        if "error" in nxt:  # should not happen; fall back to any legal move
            print("engine move rejected:", uci, nxt["error"])
            nxt = _req(base, f"/api/games/{slot}/move", {"move": st["legal_moves"][0]})
        st = nxt
        if len(searcher.tt) > 2_000_000:
            searcher.tt.clear()
    print(f"game {slot}: {st['result']} ({st['your_outcome']}, {st['termination']}) after {st['plies_played']} plies")


if __name__ == "__main__":
    base = find_base()
    for slot in (1, 2, 3, 4):
        play(base, slot)
