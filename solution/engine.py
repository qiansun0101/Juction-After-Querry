"""Small dependency-free chess engine used by the reference solution.

Board representation: 120-character mailbox, always rotated so the side to move
is "uppercase" and moves "up" the board. Search: iterative-deepening
negamax alpha-beta with a transposition table, null-move pruning, MVV-LVA
ordering, killer moves and a capture-only quiescence search. Illegal moves
(leaving the king in check) are filtered by a king-capture test.
"""

from __future__ import annotations

import time
from collections import namedtuple

A1, H1, A8, H8 = 91, 98, 21, 28
N, E, S, W = -10, 1, 10, -1
DIRS = {
    "P": (N, N + N, N + W, N + E),
    "N": (N + N + E, E + N + E, E + S + E, S + S + E, S + S + W, W + S + W, W + N + W, N + N + W),
    "B": (N + E, S + E, S + W, N + W),
    "R": (N, E, S, W),
    "Q": (N, E, S, W, N + E, S + E, S + W, N + W),
    "K": (N, E, S, W, N + E, S + E, S + W, N + W),
}
PIECE = {"P": 100, "N": 320, "B": 333, "R": 510, "Q": 930, "K": 60000}
# Piece-square tables from White's view, a8..h8 first row.
_PST = {
    "P": (0, 0, 0, 0, 0, 0, 0, 0,
          78, 83, 86, 73, 102, 82, 85, 90,
          7, 29, 21, 44, 40, 31, 44, 7,
          -17, 16, -2, 15, 14, 0, 15, -13,
          -26, 3, 10, 9, 6, 1, 0, -23,
          -22, 9, 5, -11, -10, -2, 3, -19,
          -31, 8, -7, -37, -36, -14, 3, -31,
          0, 0, 0, 0, 0, 0, 0, 0),
    "N": (-66, -53, -75, -75, -10, -55, -58, -70,
          -3, -6, 100, -36, 4, 62, -4, -14,
          10, 67, 1, 74, 73, 27, 62, -2,
          24, 24, 45, 37, 33, 41, 25, 17,
          -1, 5, 31, 21, 22, 35, 2, 0,
          -18, 10, 13, 22, 18, 15, 11, -14,
          -23, -15, 2, 0, 2, 0, -23, -20,
          -74, -23, -26, -24, -19, -35, -22, -69),
    "B": (-59, -78, -82, -76, -23, -107, -37, -50,
          -11, 20, 35, -42, -39, 31, 2, -22,
          -9, 39, -32, 41, 52, -10, 28, -14,
          25, 17, 20, 34, 26, 25, 15, 10,
          13, 10, 17, 23, 17, 16, 0, 7,
          14, 25, 24, 15, 8, 25, 20, 15,
          19, 20, 11, 6, 7, 6, 20, 16,
          -7, 2, -15, -12, -14, -15, -10, -10),
    "R": (35, 29, 33, 4, 37, 33, 56, 50,
          55, 29, 56, 67, 55, 62, 34, 60,
          19, 35, 28, 33, 45, 27, 25, 15,
          0, 5, 16, 13, 18, -4, -9, -6,
          -28, -35, -16, -21, -13, -29, -46, -30,
          -42, -28, -42, -25, -25, -35, -26, -46,
          -53, -38, -31, -26, -29, -43, -44, -53,
          -30, -24, -18, 5, -2, -18, -31, -32),
    "Q": (6, 1, -8, -104, 69, 24, 88, 26,
          14, 32, 60, -10, 20, 76, 57, 24,
          -2, 43, 32, 60, 72, 63, 43, 2,
          1, -16, 22, 17, 25, 20, -13, -6,
          -14, -15, -2, -5, -1, -10, -20, -22,
          -30, -6, -13, -11, -16, -11, -16, -27,
          -36, -18, 0, -19, -15, -15, -21, -38,
          -39, -30, -31, -13, -31, -36, -34, -42),
    "K": (4, 54, 47, -99, -99, 60, 83, -62,
          -32, 10, 55, 56, 56, 55, 10, 3,
          -62, 12, -57, 44, -67, 28, 37, -31,
          -55, 50, 11, -4, -19, 13, 0, -49,
          -55, -43, -52, -28, -51, -47, -8, -50,
          -47, -42, -43, -79, -64, -32, -29, -32,
          -4, 3, -14, -50, -57, -18, 13, 4,
          17, 30, -3, -14, 6, -1, 40, 18),
}
PST = {}
for _k, _t in _PST.items():
    rows = [(0,) + tuple(x + PIECE[_k] for x in _t[i * 8 : i * 8 + 8]) + (0,) for i in range(8)]
    PST[_k] = (0,) * 20 + sum(rows, ()) + (0,) * 20

MATE_LOWER = PIECE["K"] - 10 * PIECE["Q"]
MATE_UPPER = PIECE["K"] + 10 * PIECE["Q"]

Move = namedtuple("Move", "i j prom")


def _rot_sq(i: int) -> int:
    return 119 - i


class Pos(namedtuple("Pos", "board score wc bc ep kp")):
    """board: 120 chars; wc/bc: castling rights (queen-side, king-side) for us/them."""

    def gen_moves(self):
        b = self.board
        for i, p in enumerate(b):
            if not p.isupper():
                continue
            for d in DIRS[p]:
                j = i + d
                while True:
                    q = b[j]
                    if q.isspace() or q.isupper():
                        break
                    if p == "P":
                        if d in (N, N + N) and q != ".":
                            break
                        if d == N + N and (i < A1 + N or b[i + N] != "."):
                            break
                        if d in (N + W, N + E) and q == "." and j not in (self.ep, self.kp, self.kp - 1, self.kp + 1):
                            break
                        if A8 <= j <= H8:
                            for pr in "NBRQ":
                                yield Move(i, j, pr)
                            break
                    yield Move(i, j, "")
                    if p in "PNK" or q.islower():
                        break
                    if i == A1 and b[j + E] == "K" and self.wc[0]:
                        yield Move(j + E, j + W, "")
                    if i == H1 and b[j + W] == "K" and self.wc[1]:
                        yield Move(j + W, j + E, "")
                    j += d

    def rotate(self, nullmove: bool = False) -> "Pos":
        return Pos(
            self.board[::-1].swapcase(),
            -self.score,
            self.bc,
            self.wc,
            _rot_sq(self.ep) if self.ep and not nullmove else 0,
            _rot_sq(self.kp) if self.kp and not nullmove else 0,
        )

    def move(self, m: Move) -> "Pos":
        i, j, prom = m
        p = self.board[i]
        b = list(self.board)
        wc, bc, ep, kp = self.wc, self.bc, 0, 0
        score = self.score + self.value(m)
        b[j] = p
        b[i] = "."
        if i == A1:
            wc = (False, wc[1])
        if i == H1:
            wc = (wc[0], False)
        if j == A8:
            bc = (bc[0], False)
        if j == H8:
            bc = (False, bc[1])
        if p == "K":
            wc = (False, False)
            if abs(j - i) == 2:
                kp = (i + j) // 2
                b[A1 if j < i else H1] = "."
                b[kp] = "R"
        if p == "P":
            if A8 <= j <= H8:
                b[j] = prom
            if j - i == 2 * N:
                ep = i + N
            if j == self.ep:
                b[j + S] = "."
        return Pos("".join(b), score, wc, bc, ep, kp).rotate()

    def value(self, m: Move) -> int:
        i, j, prom = m
        p, q = self.board[i], self.board[j]
        score = PST[p][j] - PST[p][i]
        if q.islower():
            score += PST[q.upper()][_rot_sq(j)]
        if abs(j - self.kp) < 2:
            score += PST["K"][_rot_sq(j)]
        if p == "K" and abs(i - j) == 2:
            score += PST["R"][(i + j) // 2]
            score -= PST["R"][A1 if j < i else H1]
        if p == "P":
            if A8 <= j <= H8:
                score += PST[prom][j] - PST["P"][j]
            if j == self.ep:
                score += PST["P"][_rot_sq(j + S)]
        return score

    def king_capturable(self) -> bool:
        """True if the side to move can capture the opponent's king (or, right after
        the opponent castled, a square the king passed through)."""
        for r in self.gen_moves():
            if self.board[r.j] == "k" or (self.kp and abs(r.j - self.kp) < 2):
                return True
        return False

    def in_check_after_null(self) -> bool:
        """True if the side NOT to move could capture our king (i.e. we are in check)."""
        r = self.rotate(nullmove=True)
        return any(r.board[m.j] == "k" for m in r.gen_moves())


def from_fen(fen: str) -> tuple[Pos, bool]:
    parts = fen.split()
    rows = parts[0].split("/")
    board = [" " * 9 + "\n", " " * 9 + "\n"]
    for row in rows:
        s = ""
        for ch in row:
            s += "." * int(ch) if ch.isdigit() else ch
        board.append(" " + s + "\n")
    board += [" " * 9 + "\n", " " * 9 + "\n"]
    bstr = "".join(board)
    white = parts[1] == "w"
    cast = parts[2]
    wc = ("Q" in cast, "K" in cast)
    bc = ("k" in cast, "q" in cast)
    ep = 0
    if parts[3] != "-":
        f = ord(parts[3][0]) - ord("a")
        r = int(parts[3][1]) - 1
        ep = A1 + f - 10 * r
    score = 0
    for i, p in enumerate(bstr):
        if p.isupper():
            score += PST[p][i]
        elif p.islower():
            score -= PST[p.upper()][_rot_sq(i)]
    pos = Pos(bstr, score, wc, bc, ep, 0)
    if not white:
        # Castling tuples are (west, east) in each side's own rotated frame.
        pos = Pos(bstr[::-1].swapcase(), -score, bc, wc, _rot_sq(ep) if ep else 0, 0)
    return pos, white


def sq_name(i: int, white: bool) -> str:
    if not white:
        i = _rot_sq(i)
    rank, fil = divmod(i - A1, 10)
    return chr(fil + ord("a")) + str(-rank + 1)


class Searcher:
    def __init__(self) -> None:
        self.tt: dict = {}
        self.killers: dict = {}
        self.nodes = 0
        self.history: set = set()

    def qsearch(self, pos: Pos, alpha: int, beta: int) -> int:
        self.nodes += 1
        if pos.score <= -MATE_LOWER:
            return -MATE_UPPER
        stand = pos.score
        if stand >= beta:
            return stand
        alpha = max(alpha, stand)
        caps = [m for m in pos.gen_moves() if pos.board[m.j].islower() or m.prom]
        caps.sort(key=pos.value, reverse=True)
        for m in caps:
            if stand + pos.value(m) + 200 < alpha:
                continue
            s = -self.qsearch(pos.move(m), -beta, -alpha)
            if s >= beta:
                return s
            alpha = max(alpha, s)
        return alpha

    def search(self, pos: Pos, depth: int, alpha: int, beta: int, ply: int, deadline: float) -> int:
        if pos.score <= -MATE_LOWER:
            return -MATE_UPPER
        if ply > 0 and pos.board in self.history:
            return 0
        if depth <= 0:
            return self.qsearch(pos, alpha, beta)
        self.nodes += 1
        if self.nodes & 1023 == 0 and time.time() > deadline:
            raise TimeoutError
        key = (pos.board, pos.wc, pos.bc, pos.ep)
        entry = self.tt.get(key)
        tt_move = None
        if entry:
            e_depth, e_score, e_flag, tt_move = entry
            if e_depth >= depth and ply > 0:
                if e_flag == 0 or (e_flag == 1 and e_score >= beta) or (e_flag == -1 and e_score <= alpha):
                    return e_score
        in_check = None
        # Null-move pruning.
        if depth >= 3 and ply > 0 and abs(beta) < MATE_LOWER and pos.score >= beta:
            in_check = pos.in_check_after_null()
            if not in_check and any(c in pos.board for c in "NBRQ"):
                s = -self.search(pos.rotate(nullmove=True), depth - 3, -beta, -beta + 1, ply + 1, deadline)
                if s >= beta:
                    return s
        moves = list(pos.gen_moves())
        killer = self.killers.get(ply)

        def order(m):
            if m == tt_move:
                return 10**9
            v = pos.value(m)
            if pos.board[m.j].islower():
                return 10**6 + PIECE[pos.board[m.j].upper()] * 10 - PIECE[pos.board[m.i]] // 10
            if m == killer:
                return 10**5
            return v

        moves.sort(key=order, reverse=True)
        best, best_move, orig_alpha, legal = -MATE_UPPER, None, alpha, 0
        for m in moves:
            child = pos.move(m)
            # King-capture legality check: reject moves that leave our king en prise.
            if child.king_capturable():
                continue
            legal += 1
            self.history.add(pos.board)
            try:
                s = -self.search(child, depth - 1, -beta, -alpha, ply + 1, deadline)
            finally:
                self.history.discard(pos.board)
            if s > best:
                best, best_move = s, m
            alpha = max(alpha, s)
            if alpha >= beta:
                if not pos.board[m.j].islower():
                    self.killers[ply] = m
                break
        if legal == 0:
            if in_check is None:
                in_check = pos.in_check_after_null()
            return -MATE_UPPER + ply if in_check else 0
        flag = 0 if orig_alpha < best < beta else (1 if best >= beta else -1)
        self.tt[key] = (depth, best, flag, best_move)
        return best

    def best_move(self, pos: Pos, seconds: float, history: set | None = None) -> Move | None:
        self.history = set(history or ())
        self.nodes = 0
        deadline = time.time() + seconds
        best = None
        for depth in range(1, 64):
            try:
                self.search(pos, depth, -MATE_UPPER, MATE_UPPER, 0, deadline)
            except TimeoutError:
                break
            e = self.tt.get((pos.board, pos.wc, pos.bc, pos.ep))
            if e and e[3] is not None:
                best = e[3]
            if time.time() > deadline - seconds * 0.55:
                break
        if best is None:  # fall back to any legal move
            for m in pos.gen_moves():
                child = pos.move(m)
                if not child.king_capturable():
                    return m
        return best


def move_to_uci(m: Move, white: bool) -> str:
    return sq_name(m.i, white) + sq_name(m.j, white) + m.prom.lower()
