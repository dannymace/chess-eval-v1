from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests


BASE_URL = "https://api.chess.com/pub"
USER_AGENT = "chess-eval-v1/0.1 (contact: local-docker-user)"


class ChessComError(RuntimeError):
    """Raised when Chess.com data cannot be fetched or parsed."""


@dataclass(slots=True)
class LatestGame:
    username: str
    game: dict[str, Any]
    archive_url: str

    @property
    def pgn(self) -> str:
        pgn = self.game.get("pgn")
        if not pgn:
            raise ChessComError("Latest game response did not include PGN.")
        return pgn


def _get_json(url: str) -> dict[str, Any]:
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=30,
    )
    if response.status_code != 200:
        raise ChessComError(
            f"Chess.com request failed for {url} with HTTP {response.status_code}."
        )
    data = response.json()
    if not isinstance(data, dict):
        raise ChessComError(f"Unexpected Chess.com payload for {url}.")
    return data


def fetch_latest_game(username: str) -> LatestGame:
    return fetch_recent_games(username, 1)[0]


def fetch_recent_games(username: str, limit: int) -> list[LatestGame]:
    if limit < 1:
        raise ChessComError("Game limit must be at least 1.")

    profile = _get_json(f"{BASE_URL}/player/{username}")
    canonical_username = profile.get("username", username)

    archives_data = _get_json(f"{BASE_URL}/player/{username}/games/archives")
    archives = archives_data.get("archives", [])
    if not archives:
        raise ChessComError(f"No public archives found for user '{username}'.")

    recent_games: list[LatestGame] = []
    for archive_url in reversed(archives):
        archive_data = _get_json(archive_url)
        games = archive_data.get("games", [])
        eligible_games = [
            game
            for game in games
            if isinstance(game, dict) and game.get("pgn") and game.get("end_time")
        ]
        if not eligible_games:
            continue

        for game in sorted(
            eligible_games,
            key=lambda item: int(item["end_time"]),
            reverse=True,
        ):
            recent_games.append(
                LatestGame(
                    username=str(canonical_username),
                    game=game,
                    archive_url=archive_url,
                )
            )
            if len(recent_games) >= limit:
                return recent_games

    if recent_games:
        return recent_games

    raise ChessComError(
        f"No finished public games with PGN were found for user '{username}'."
    )
