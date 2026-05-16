from __future__ import annotations

import argparse
import sys

from .analyzer import analyze_latest_game, render_report
from .chesscom import ChessComError, fetch_latest_game


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
        default=2,
        help="Number of Stockfish threads",
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
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
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

    print(render_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
