from __future__ import annotations

import argparse
import sys

from .analyzer import (
    analyze_latest_game,
    build_trend_report,
    render_report,
    render_trend_report,
)
from .chesscom import ChessComError, fetch_latest_game, fetch_recent_games


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch the latest finished public Chess.com game for a user and "
            "analyze it locally with Stockfish."
        )
    )
    parser.add_argument("username", help="Chess.com username")
    parser.add_argument(
        "--engine-path",
        default="/usr/games/stockfish",
        help="Path to the local Stockfish binary",
    )
    parser.add_argument(
        "--depth",
        type=int,
        default=11,
        help="Search depth for Stockfish analysis",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=0,
        help="Number of Stockfish threads; 0 uses all CPUs visible to the container",
    )
    parser.add_argument(
        "--hash-mb",
        type=int,
        default=256,
        help="Stockfish hash size in megabytes",
    )
    parser.add_argument(
        "--multipv",
        type=int,
        default=3,
        help="Number of top candidate moves to include",
    )
    parser.add_argument(
        "--max-mistakes",
        type=int,
        default=3,
        help="How many major mistakes to show",
    )
    parser.add_argument(
        "--last",
        type=int,
        default=1,
        help="Analyze the last N finished public games and summarize trends",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.last < 1:
            raise ValueError("--last must be at least 1.")

        if args.last == 1:
            latest_game = fetch_latest_game(args.username)
            report = analyze_latest_game(
                latest_game,
                engine_path=args.engine_path,
                depth=args.depth,
                threads=args.threads,
                hash_mb=args.hash_mb,
                multipv=args.multipv,
                max_mistakes=args.max_mistakes,
            )
            print(render_report(report))
        else:
            recent_games = fetch_recent_games(args.username, args.last)
            reports = [
                analyze_latest_game(
                    game,
                    engine_path=args.engine_path,
                    depth=args.depth,
                    threads=args.threads,
                    hash_mb=args.hash_mb,
                    multipv=args.multipv,
                    max_mistakes=args.max_mistakes,
                )
                for game in recent_games
            ]
            print(render_trend_report(build_trend_report(args.username, reports)))
    except ChessComError as exc:
        print(f"Chess.com error: {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError:
        print(
            f"Stockfish binary not found at '{args.engine_path}'.",
            file=sys.stderr,
        )
        return 3
    except Exception as exc:
        print(f"Analysis failed: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
