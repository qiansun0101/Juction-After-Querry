"""Chess Gauntlet arena server: MCP tools (/mcp) + an equivalent JSON REST API (/api)."""

from __future__ import annotations

import hmac
import os

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from arena import Arena, ArenaError

ADMIN_TOKEN = os.environ.get("ARENA_ADMIN_TOKEN", "")
arena = Arena()
mcp = FastMCP(
    "chess-arena",
    instructions=(
        "Chess Gauntlet arena. Four games against a ladder of increasingly strong "
        "opponents. Use list_games, start_game, get_state, make_move and resign."
    ),
)


def _call(fn, *args):
    try:
        return fn(*args)
    except ArenaError as e:
        return {"error": str(e)}


@mcp.tool
def list_games() -> dict:
    """List the four gauntlet games: opponent, your colour, status and result."""
    return arena.overview()


@mcp.tool
def start_game(slot: int) -> dict:
    """Start game `slot` (1-4). Each game can be started once, and only one game may be
    in progress at a time. If you play Black the opponent's first move is already made."""
    return _call(arena.start, slot)


@mcp.tool
def get_state(slot: int) -> dict:
    """Current position of game `slot`: FEN, ASCII board, move history, legal moves (SAN)."""
    return _call(arena.state, slot)


@mcp.tool
def make_move(slot: int, move: str) -> dict:
    """Play `move` (SAN like 'Nf3', 'O-O', 'exd8=Q' or UCI like 'g1f3') in game `slot`.
    The opponent replies immediately; the returned state includes its reply."""
    return _call(arena.move, slot, move)


@mcp.tool
def resign(slot: int) -> dict:
    """Resign game `slot` (counts as a loss)."""
    return _call(arena.resign, slot)


def _json(payload: dict) -> JSONResponse:
    return JSONResponse(payload, status_code=400 if "error" in payload else 200)


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


@mcp.custom_route("/api/games", methods=["GET"])
async def api_games(_: Request) -> JSONResponse:
    return _json(arena.overview())


@mcp.custom_route("/api/games/{slot}", methods=["GET"])
async def api_state(request: Request) -> JSONResponse:
    return _json(_call(arena.state, request.path_params["slot"]))


@mcp.custom_route("/api/games/{slot}/start", methods=["POST"])
async def api_start(request: Request) -> JSONResponse:
    return _json(_call(arena.start, request.path_params["slot"]))


@mcp.custom_route("/api/games/{slot}/move", methods=["POST"])
async def api_move(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        body = {}
    move = body.get("move") if isinstance(body, dict) else None
    if not isinstance(move, str):
        return _json({"error": 'POST a JSON body like {"move": "e4"}'})
    return _json(_call(arena.move, request.path_params["slot"], move))


@mcp.custom_route("/api/games/{slot}/resign", methods=["POST"])
async def api_resign(request: Request) -> JSONResponse:
    return _json(_call(arena.resign, request.path_params["slot"]))


@mcp.custom_route("/admin/results", methods=["GET"])
async def admin_results(request: Request) -> JSONResponse:
    token = request.headers.get("x-admin-token", "")
    if not ADMIN_TOKEN or not hmac.compare_digest(token, ADMIN_TOKEN):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    return JSONResponse(arena.admin_results())


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
