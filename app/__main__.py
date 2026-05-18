from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from . import __version__
from .analyzer import (
    GameReport,
    TrendReport,
    analyze_latest_game,
    build_trend_report,
    render_html_report,
    render_html_trend_report,
    render_report,
    render_trend_report,
)
from .chesscom import ChessComError, fetch_latest_game, fetch_recent_games


REPORT_DIR_ENV = "CHESS_EVAL_REPORT_DIR"
DEFAULT_REPORT_DIR = "reports"


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
    parser.add_argument(
        "--html",
        help="Override the automatic standalone HTML report path",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"chess-eval-v1 {__version__}",
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
            _write_html(
                _resolve_html_path(args.html, _single_report_filename(report)),
                render_html_report(report),
            )
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
            trend_report = build_trend_report(args.username, reports)
            print(render_trend_report(trend_report))
            _write_html(
                _resolve_html_path(
                    args.html,
                    _trend_report_filename(trend_report, args.last),
                ),
                render_html_trend_report(trend_report),
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

    return 0


def _resolve_html_path(path: str | None, filename: str) -> Path:
    if not path:
        return Path(os.environ.get(REPORT_DIR_ENV, DEFAULT_REPORT_DIR)) / filename

    output_path = Path(path)
    if path.endswith(("/", "\\")) or output_path.suffix.lower() != ".html":
        return output_path / filename
    return output_path


def _single_report_filename(report: GameReport) -> str:
    parts = [report.game_date, _safe_file_part(report.opponent)]
    if report.game_id:
        parts.append(_safe_file_part(report.game_id))
    return "_".join(part for part in parts if part) + ".html"


def _trend_report_filename(report: TrendReport, requested_count: int) -> str:
    report_date = report.games[0].game_date
    username = _safe_file_part(report.username)
    return f"{report_date}_{username}_last-{requested_count}.html"


def _safe_file_part(value: str) -> str:
    safe_value = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip()).strip("-").lower()
    return safe_value or "unknown"


def _write_html(path: Path, html: str) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    print(f"HTML report written to {output_path}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
