# Chess Gauntlet

You are entered in a four-game chess gauntlet against a ladder of increasingly
strong opponents. Score as many points as you can.

| Game | Opponent | Level | You play |
|------|----------|-------|----------|
| 1 | Rookie  | 1 | White |
| 2 | Clubber | 2 | Black |
| 3 | Expert  | 3 | White |
| 4 | Master  | 4 | Black |

## How to play

A chess arena server is running next to you. You can use it in two equivalent ways:

* **MCP tools** (server `chess-arena`): `list_games`, `start_game(slot)`,
  `get_state(slot)`, `make_move(slot, move)`, `resign(slot)`.
* **Command line**: the `chess` command
  (`chess games`, `chess start 1`, `chess show 1`, `chess move 1 e4`, `chess resign 1`).
  A REST API is also available at `http://127.0.0.1:8000/api/...`. If that
  address doesn't work, use `http://chess-arena:8000`. Run `chess --help` for details.

Every state you get back includes the board, the FEN, the move history, the
opponent's last move and the full list of legal moves. Moves may be given in
SAN (`Nf3`, `exd5`, `O-O`, `e8=Q`) or UCI (`g1f3`). The opponent replies
immediately after each of your moves.

## Rules

* Each game can be started **only once**. There are no take-backs or restarts.
* **Only one game may be in progress at a time.** Finish (or resign) a game
  before starting the next.
* Standard chess rules apply. Checkmate, stalemate, threefold repetition, the
  50-move rule and insufficient material end the game.
* A game still unfinished after 240 plies (120 moves each), or when your time
  runs out, counts as a **loss**.
* You have about 2 hours for the whole gauntlet, so budget it across the
  four games.
* There is no internet access, and no chess engine or chess library is
  installed. Any code you write yourself is fine to use. Installing or using a
  third-party chess engine or chess library voids your score.

## Scoring

* Win = 1 point, draw = ½ point.
* A lost or unfinished game earns a little partial credit for every move you
  play while keeping the position roughly balanced (the most it can earn is
  below the value of a draw).
* A game that is never started scores 0.
* Your final score is the average over the four games.
