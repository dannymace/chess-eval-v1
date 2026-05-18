from __future__ import annotations

import io
import os
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
from math import exp
from statistics import mean
from urllib.parse import unquote, urlparse

import chess
import chess.engine
import chess.pgn
import chess.svg

from .chesscom import LatestGame


MATE_SCORE = 100_000


@dataclass(slots=True)
class CandidateMove:
    san: str
    score: str


@dataclass(slots=True)
class Mistake:
    move_label: str
    phase: str
    played: str
    played_uci: str
    best: str
    best_uci: str
    fen: str
    best_score: str
    played_score: str
    cp_loss: int
    expected_points_loss: float
    severity: str
    note: str
    top_lines: list[CandidateMove]


@dataclass(slots=True)
class GameReport:
    username: str
    color: str
    result: str
    opening: str
    time_class: str
    url: str
    end_time: str
    player_rating: int | None
    total_player_moves: int
    accuracy_rating: float
    accuracy_label: str
    average_cp_loss: float
    inaccuracies: int
    mistakes: int
    misses: int
    blunders: int
    flagged_moves: list[Mistake]
    top_mistakes: list[Mistake]
    takeaway: str


@dataclass(slots=True)
class TrendReport:
    username: str
    games: list[GameReport]
    total_player_moves: int
    average_accuracy: float
    average_cp_loss: float
    inaccuracies: int
    mistakes: int
    misses: int
    blunders: int
    common_openings: list[tuple[str, int]]
    phase_counts: dict[str, int]
    recurring_lessons: list[str]


def analyze_latest_game(
    latest_game: LatestGame,
    *,
    engine_path: str,
    depth: int,
    threads: int,
    hash_mb: int,
    multipv: int,
    max_mistakes: int,
) -> GameReport:
    game = chess.pgn.read_game(io.StringIO(latest_game.pgn))
    if game is None:
        raise RuntimeError("Could not parse PGN from Chess.com.")

    white_name = game.headers.get("White", "")
    black_name = game.headers.get("Black", "")
    username = latest_game.username

    if white_name.lower() == username.lower():
        player_color = chess.WHITE
        color_name = "White"
        player_result = latest_game.game.get("white", {}).get("result", "")
        player_rating = _parse_rating(game.headers.get("WhiteElo", ""))
    elif black_name.lower() == username.lower():
        player_color = chess.BLACK
        color_name = "Black"
        player_result = latest_game.game.get("black", {}).get("result", "")
        player_rating = _parse_rating(game.headers.get("BlackElo", ""))
    else:
        raise RuntimeError(
            f"Latest game PGN did not match requested user '{username}'. "
            f"PGN players were '{white_name}' and '{black_name}'."
        )

    board = game.board()
    limit = chess.engine.Limit(depth=depth)
    mistakes: list[Mistake] = []
    cp_losses: list[int] = []
    player_moves = 0
    stockfish_threads = _resolve_threads(threads)

    with chess.engine.SimpleEngine.popen_uci(engine_path) as engine:
        engine.configure(
            {
                "Threads": stockfish_threads,
                "Hash": hash_mb,
                "UCI_ShowWDL": True,
            }
        )

        for move in game.mainline_moves():
            mover = board.turn
            san = board.san(move)

            if mover == player_color:
                player_moves += 1
                best_lines = engine.analyse(board, limit, multipv=multipv)
                if isinstance(best_lines, dict):
                    best_lines = [best_lines]

                best_info = best_lines[0]
                best_move = best_info["pv"][0]
                best_score = best_info["score"].pov(player_color)
                best_san = board.san(best_move)

                matching_line = next(
                    (
                        info
                        for info in best_lines
                        if info.get("pv") and info["pv"][0] == move
                    ),
                    None,
                )

                if matching_line is not None:
                    played_score = matching_line["score"].pov(player_color)
                else:
                    after_board = board.copy(stack=False)
                    after_board.push(move)
                    played_info = engine.analyse(after_board, limit)
                    played_score = played_info["score"].pov(player_color)

                cp_loss = max(
                    0,
                    _score_to_numeric(best_score) - _score_to_numeric(played_score),
                )
                cp_losses.append(cp_loss)

                expected_points_loss = _expected_points_loss(
                    best_score,
                    played_score,
                    player_rating,
                )
                severity = _classify_severity(
                    best_score,
                    played_score,
                    expected_points_loss,
                    player_rating,
                )
                if severity is not None:
                    mistakes.append(
                        Mistake(
                            move_label=_move_label(board, san),
                            phase=_phase_name(board),
                            played=san,
                            played_uci=move.uci(),
                            best=best_san,
                            best_uci=best_move.uci(),
                            fen=board.fen(),
                            best_score=_format_score(best_score),
                            played_score=_format_score(played_score),
                            cp_loss=cp_loss,
                            expected_points_loss=expected_points_loss,
                            severity=severity,
                            note=_mistake_note(
                                board,
                                move,
                                best_move,
                                cp_loss,
                                severity,
                            ),
                            top_lines=[
                                CandidateMove(
                                    san=board.san(info["pv"][0]),
                                    score=_format_score(
                                        info["score"].pov(player_color)
                                    ),
                                )
                                for info in best_lines
                                if info.get("pv")
                            ],
                        )
                    )

            board.push(move)

    sorted_mistakes = sorted(
        mistakes,
        key=lambda item: (
            item.expected_points_loss,
            _severity_rank(item.severity),
            item.cp_loss,
        ),
        reverse=True,
    )
    top_mistakes = sorted_mistakes[:max_mistakes]
    accuracy_rating = _accuracy_rating(cp_losses)

    return GameReport(
        username=username,
        color=color_name,
        result=_normalize_result(player_result),
        opening=_format_opening(game.headers),
        time_class=str(latest_game.game.get("time_class", "unknown")),
        url=str(latest_game.game.get("url", "")),
        end_time=_format_timestamp(int(latest_game.game["end_time"])),
        player_rating=player_rating,
        total_player_moves=player_moves,
        accuracy_rating=accuracy_rating,
        accuracy_label=_accuracy_label(accuracy_rating),
        average_cp_loss=mean(cp_losses) if cp_losses else 0.0,
        inaccuracies=sum(1 for item in mistakes if item.severity == "Inaccuracy"),
        mistakes=sum(1 for item in mistakes if item.severity == "Mistake"),
        misses=sum(1 for item in mistakes if item.severity == "Miss"),
        blunders=sum(1 for item in mistakes if item.severity == "Blunder"),
        flagged_moves=sorted_mistakes,
        top_mistakes=top_mistakes,
        takeaway=_build_takeaway(top_mistakes),
    )


def build_trend_report(username: str, reports: list[GameReport]) -> TrendReport:
    if not reports:
        raise ValueError("At least one game report is required.")

    serious_moves = [
        item
        for report in reports
        for item in report.flagged_moves
        if item.severity != "Inaccuracy"
    ]
    opening_counts = Counter(report.opening for report in reports)
    phase_counts = Counter(item.phase for item in serious_moves)

    return TrendReport(
        username=username,
        games=reports,
        total_player_moves=sum(report.total_player_moves for report in reports),
        average_accuracy=mean(report.accuracy_rating for report in reports),
        average_cp_loss=mean(report.average_cp_loss for report in reports),
        inaccuracies=sum(report.inaccuracies for report in reports),
        mistakes=sum(report.mistakes for report in reports),
        misses=sum(report.misses for report in reports),
        blunders=sum(report.blunders for report in reports),
        common_openings=opening_counts.most_common(5),
        phase_counts=dict(phase_counts),
        recurring_lessons=_build_recurring_lessons(reports),
    )


def render_report(report: GameReport) -> str:
    lines = [
        f"# Chess Eval V1: {report.username}",
        "",
        f"- Color: {report.color}",
        f"- Result: {report.result}",
        f"- Opening: {report.opening}",
        f"- Time class: {report.time_class}",
        f"- Ended: {report.end_time}",
    ]
    if report.player_rating is not None:
        lines.append(f"- Player rating: {report.player_rating}")
    if report.url:
        lines.append(f"- Game URL: {report.url}")

    lines.extend(
        [
            "",
            "## Accuracy Snapshot",
            f"- Player moves analyzed: {report.total_player_moves}",
            f"- Accuracy rating: {report.accuracy_rating:.1f}/100 ({report.accuracy_label})",
            f"- Average centipawn loss: {report.average_cp_loss:.1f}",
            f"- Inaccuracies: {report.inaccuracies}",
            f"- Mistakes: {report.mistakes}",
            f"- Misses: {report.misses}",
            f"- Blunders: {report.blunders}",
            "",
            "## Biggest Moments",
        ]
    )

    if not report.top_mistakes:
        lines.append("- No major mistakes were flagged at the chosen depth.")
    else:
        for item in report.top_mistakes:
            candidate_text = ", ".join(
                f"{candidate.san} ({candidate.score})" for candidate in item.top_lines[:3]
            )
            lines.extend(
                [
                    f"- {item.move_label} [{item.phase}] {item.severity}: played `{item.played}` instead of `{item.best}`.",
                    f"  Expected-points loss: {item.expected_points_loss:.2f}. Eval swing: {item.cp_loss} cp.",
                    f"  Best line {item.best_score}; played line {item.played_score}.",
                    f"  Note: {item.note}",
                    f"  Engine candidates: {candidate_text}",
                ]
            )

    lines.extend(
        [
            "",
            "## Coaching Takeaway",
            report.takeaway,
        ]
    )

    return "\n".join(lines)


def render_trend_report(report: TrendReport) -> str:
    lines = [
        f"# Chess Eval Trend: {report.username}",
        "",
        f"- Games analyzed: {len(report.games)}",
        f"- Player moves analyzed: {report.total_player_moves}",
        f"- Average accuracy: {report.average_accuracy:.1f}/100 ({_accuracy_label(report.average_accuracy)})",
        f"- Average centipawn loss: {report.average_cp_loss:.1f}",
        f"- Inaccuracies: {report.inaccuracies}",
        f"- Mistakes: {report.mistakes}",
        f"- Misses: {report.misses}",
        f"- Blunders: {report.blunders}",
        "",
        "## Recurring Lessons",
    ]

    for lesson in report.recurring_lessons:
        lines.append(f"- {lesson}")

    lines.extend(["", "## Common Openings"])
    for opening, count in report.common_openings:
        lines.append(f"- {opening}: {count} game{_plural(count)}")

    if report.phase_counts:
        lines.extend(["", "## Serious Issues By Phase"])
        for phase, count in sorted(
            report.phase_counts.items(),
            key=lambda item: item[1],
            reverse=True,
        ):
            lines.append(f"- {phase}: {count}")

    lines.extend(["", "## Recent Games"])
    for game in report.games:
        lines.append(
            f"- {game.end_time}: {game.color} {game.result}, "
            f"{game.accuracy_rating:.1f}/100, "
            f"I/Mistake/Miss/B {game.inaccuracies}/{game.mistakes}/{game.misses}/{game.blunders}, "
            f"{game.opening}"
        )

    return "\n".join(lines)


def render_html_report(report: GameReport) -> str:
    moment_cards = "\n".join(
        _render_moment_card(item, report.color) for item in report.top_mistakes
    )
    if not moment_cards:
        moment_cards = (
            '<section class="empty">No major mistakes were flagged at the chosen depth.</section>'
        )

    meta_rows = [
        ("Color", report.color),
        ("Result", report.result),
        ("Opening", report.opening),
        ("Time class", report.time_class),
        ("Ended", report.end_time),
    ]
    if report.player_rating is not None:
        meta_rows.append(("Player rating", str(report.player_rating)))

    return _html_document(
        title=f"Chess Eval V1: {report.username}",
        body=f"""
<header class="hero">
  <p class="eyebrow">Chess Eval V1</p>
  <h1>{escape(report.username)}</h1>
  <p class="lede">{escape(report.takeaway)}</p>
</header>

<main>
  <section class="summary-grid">
    {_metric_card("Accuracy", f"{report.accuracy_rating:.1f}", f"{report.accuracy_label} / 100")}
    {_metric_card("Average loss", f"{report.average_cp_loss:.1f}", "centipawns")}
    {_metric_card("Moves", str(report.total_player_moves), "player moves analyzed")}
    {_metric_card("Issues", str(report.mistakes + report.misses + report.blunders), "mistakes, misses, blunders")}
  </section>

  <section class="panel">
    <div class="section-head">
      <p class="eyebrow">Game</p>
      <h2>Context</h2>
    </div>
    <dl class="meta-list">
      {_render_meta_rows(meta_rows)}
    </dl>
    {_game_link(report.url)}
  </section>

  <section class="panel">
    <div class="section-head">
      <p class="eyebrow">Review</p>
      <h2>Biggest Moments</h2>
    </div>
    <div class="legend">
      <span><i class="dot best"></i> Best move</span>
      <span><i class="dot played"></i> Played move</span>
    </div>
    <div class="moments">{moment_cards}</div>
  </section>
</main>
""",
    )


def render_html_trend_report(report: TrendReport) -> str:
    top_moments = sorted(
        (
            (game, item)
            for game in report.games
            for item in game.top_mistakes
        ),
        key=lambda pair: (
            pair[1].expected_points_loss,
            _severity_rank(pair[1].severity),
            pair[1].cp_loss,
        ),
        reverse=True,
    )[:8]
    moment_cards = "\n".join(
        _render_moment_card(item, game.color, subtitle=f"{game.end_time} - {game.opening}")
        for game, item in top_moments
    )
    if not moment_cards:
        moment_cards = '<section class="empty">No major moments were flagged.</section>'

    opening_rows = "\n".join(
        f"<li><span>{escape(opening)}</span><strong>{count}</strong></li>"
        for opening, count in report.common_openings
    )
    phase_rows = "\n".join(
        f"<li><span>{escape(phase)}</span><strong>{count}</strong></li>"
        for phase, count in sorted(
            report.phase_counts.items(),
            key=lambda item: item[1],
            reverse=True,
        )
    )
    lesson_rows = "\n".join(
        f"<li>{escape(lesson)}</li>" for lesson in report.recurring_lessons
    )

    return _html_document(
        title=f"Chess Eval Trend: {report.username}",
        body=f"""
<header class="hero">
  <p class="eyebrow">Chess Eval Trend</p>
  <h1>{escape(report.username)}</h1>
  <p class="lede">A review of the last {len(report.games)} public game{_plural(len(report.games))}, focused on repeated patterns rather than one-off engine verdicts.</p>
</header>

<main>
  <section class="summary-grid">
    {_metric_card("Average accuracy", f"{report.average_accuracy:.1f}", f"{_accuracy_label(report.average_accuracy)} / 100")}
    {_metric_card("Average loss", f"{report.average_cp_loss:.1f}", "centipawns")}
    {_metric_card("Games", str(len(report.games)), "recent games analyzed")}
    {_metric_card("Serious issues", str(report.mistakes + report.misses + report.blunders), "mistakes, misses, blunders")}
  </section>

  <section class="panel">
    <div class="section-head">
      <p class="eyebrow">Training</p>
      <h2>Recurring Lessons</h2>
    </div>
    <ul class="lesson-list">{lesson_rows}</ul>
  </section>

  <section class="split">
    <div class="panel">
      <div class="section-head">
        <p class="eyebrow">Openings</p>
        <h2>Common Lines</h2>
      </div>
      <ul class="rank-list">{opening_rows}</ul>
    </div>
    <div class="panel">
      <div class="section-head">
        <p class="eyebrow">Phases</p>
        <h2>Serious Issues</h2>
      </div>
      <ul class="rank-list">{phase_rows}</ul>
    </div>
  </section>

  <section class="panel">
    <div class="section-head">
      <p class="eyebrow">Review</p>
      <h2>Biggest Moments</h2>
    </div>
    <div class="legend">
      <span><i class="dot best"></i> Best move</span>
      <span><i class="dot played"></i> Played move</span>
    </div>
    <div class="moments">{moment_cards}</div>
  </section>
</main>
""",
    )


def _html_document(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>{escape(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #172118;
      --muted: #637061;
      --paper: #f6f2e9;
      --panel: #fffdf7;
      --line: #d9d0bf;
      --green: #2f8a4b;
      --red: #c2412d;
      --gold: #bd7a23;
      --blue: #286d8f;
      --shadow: 0 18px 45px rgba(38, 31, 19, 0.12);
    }}

    * {{ box-sizing: border-box; }}

    body {{
      margin: 0;
      color: var(--ink);
      background:
        linear-gradient(135deg, rgba(255, 255, 255, 0.72), rgba(255, 255, 255, 0.2)),
        radial-gradient(circle at top left, rgba(47, 138, 75, 0.18), transparent 34rem),
        radial-gradient(circle at bottom right, rgba(189, 122, 35, 0.14), transparent 30rem),
        var(--paper);
      font-family: Georgia, "Times New Roman", serif;
      line-height: 1.45;
    }}

    .hero {{
      padding: 56px clamp(20px, 5vw, 72px) 28px;
      border-bottom: 1px solid rgba(23, 33, 24, 0.12);
    }}

    .eyebrow {{
      margin: 0 0 10px;
      color: var(--green);
      font-family: "Trebuchet MS", Verdana, sans-serif;
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }}

    h1, h2, h3, p {{ margin-top: 0; }}

    h1 {{
      max-width: 980px;
      margin-bottom: 12px;
      font-size: clamp(2.3rem, 8vw, 5.8rem);
      line-height: 0.95;
      letter-spacing: 0;
    }}

    h2 {{
      margin-bottom: 0;
      font-size: clamp(1.45rem, 2vw, 2.1rem);
      letter-spacing: 0;
    }}

    h3 {{
      margin-bottom: 6px;
      font-size: 1.15rem;
      letter-spacing: 0;
    }}

    .lede {{
      max-width: 820px;
      margin-bottom: 0;
      color: var(--muted);
      font-size: 1.08rem;
    }}

    main {{
      width: min(1180px, calc(100% - 32px));
      margin: 0 auto;
      padding: 28px 0 56px;
    }}

    .summary-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 14px;
      margin-bottom: 18px;
    }}

    .metric, .panel, .moment-card {{
      background: rgba(255, 253, 247, 0.92);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }}

    .metric {{
      padding: 18px;
      min-height: 112px;
    }}

    .metric .label {{
      display: block;
      color: var(--muted);
      font-family: "Trebuchet MS", Verdana, sans-serif;
      font-size: 0.78rem;
      font-weight: 700;
      text-transform: uppercase;
    }}

    .metric .value {{
      display: block;
      margin-top: 10px;
      font-size: clamp(2rem, 4vw, 3.1rem);
      font-weight: 700;
      line-height: 1;
    }}

    .metric .hint {{
      display: block;
      margin-top: 7px;
      color: var(--muted);
      font-size: 0.92rem;
    }}

    .panel {{
      margin-top: 18px;
      padding: clamp(18px, 3vw, 30px);
    }}

    .section-head {{
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 18px;
      margin-bottom: 18px;
      border-bottom: 1px solid var(--line);
      padding-bottom: 14px;
    }}

    .section-head .eyebrow {{ margin-bottom: 4px; }}

    .meta-list {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 14px;
      margin: 0;
    }}

    .meta-list div {{
      border-left: 3px solid rgba(47, 138, 75, 0.35);
      padding-left: 12px;
    }}

    dt {{
      color: var(--muted);
      font-family: "Trebuchet MS", Verdana, sans-serif;
      font-size: 0.76rem;
      font-weight: 700;
      text-transform: uppercase;
    }}

    dd {{
      margin: 4px 0 0;
      font-size: 1rem;
      font-weight: 700;
    }}

    .game-link {{
      display: inline-flex;
      margin-top: 18px;
      color: var(--green);
      font-family: "Trebuchet MS", Verdana, sans-serif;
      font-weight: 700;
      text-decoration: none;
    }}

    .legend {{
      display: flex;
      flex-wrap: wrap;
      gap: 16px;
      margin-bottom: 16px;
      color: var(--muted);
      font-family: "Trebuchet MS", Verdana, sans-serif;
      font-size: 0.9rem;
    }}

    .dot {{
      display: inline-block;
      width: 11px;
      height: 11px;
      margin-right: 7px;
      border-radius: 50%;
      vertical-align: -1px;
    }}

    .dot.best {{ background: var(--green); }}
    .dot.played {{ background: var(--red); }}

    .moments {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 18px;
    }}

    .moment-card {{
      display: grid;
      grid-template-columns: minmax(260px, 380px) minmax(0, 1fr);
      gap: clamp(18px, 3vw, 30px);
      padding: clamp(14px, 2vw, 22px);
      box-shadow: none;
    }}

    .board-wrap {{
      width: 100%;
      align-self: start;
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #e2d4bd;
    }}

    .board-wrap svg {{
      display: block;
      width: 100%;
      height: auto;
    }}

    .moment-body {{
      min-width: 0;
    }}

    .badge {{
      display: inline-flex;
      align-items: center;
      margin-bottom: 12px;
      padding: 5px 9px;
      border-radius: 999px;
      color: #fff;
      font-family: "Trebuchet MS", Verdana, sans-serif;
      font-size: 0.78rem;
      font-weight: 700;
    }}

    .badge.inaccuracy {{ background: var(--blue); }}
    .badge.mistake {{ background: var(--gold); }}
    .badge.miss {{ background: #9b4d9a; }}
    .badge.blunder {{ background: var(--red); }}

    .subtitle {{
      margin-bottom: 8px;
      color: var(--muted);
      font-size: 0.95rem;
    }}

    .move-line {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin: 14px 0;
    }}

    .move-pill {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 9px 11px;
      background: #faf5e9;
      font-family: "Trebuchet MS", Verdana, sans-serif;
      font-size: 0.95rem;
    }}

    .move-pill strong {{
      color: var(--ink);
    }}

    .detail-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      margin: 14px 0;
    }}

    .detail-grid div {{
      border-top: 1px solid var(--line);
      padding-top: 10px;
    }}

    .detail-grid span {{
      display: block;
      color: var(--muted);
      font-family: "Trebuchet MS", Verdana, sans-serif;
      font-size: 0.75rem;
      font-weight: 700;
      text-transform: uppercase;
    }}

    .detail-grid strong {{
      display: block;
      margin-top: 4px;
      font-size: 1rem;
    }}

    .note {{
      margin: 12px 0;
      color: var(--muted);
    }}

    .candidate-list {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      padding: 0;
      margin: 12px 0 0;
      list-style: none;
    }}

    .candidate-list li {{
      border: 1px solid rgba(47, 138, 75, 0.24);
      border-radius: 999px;
      padding: 6px 9px;
      background: rgba(47, 138, 75, 0.07);
      font-family: "Trebuchet MS", Verdana, sans-serif;
      font-size: 0.86rem;
    }}

    .split {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 18px;
    }}

    .rank-list, .lesson-list {{
      padding: 0;
      margin: 0;
      list-style: none;
    }}

    .rank-list li {{
      display: flex;
      justify-content: space-between;
      gap: 18px;
      border-bottom: 1px solid var(--line);
      padding: 12px 0;
    }}

    .rank-list li:last-child {{ border-bottom: 0; }}

    .lesson-list li {{
      border-left: 3px solid var(--green);
      padding: 0 0 0 14px;
      margin: 0 0 16px;
    }}

    .empty {{
      padding: 24px;
      border: 1px dashed var(--line);
      border-radius: 8px;
      color: var(--muted);
    }}

    @media (max-width: 880px) {{
      .summary-grid, .split, .meta-list {{
        grid-template-columns: 1fr 1fr;
      }}

      .moment-card {{
        grid-template-columns: 1fr;
      }}

      .board-wrap {{
        max-width: 420px;
      }}
    }}

    @media (max-width: 560px) {{
      .hero {{
        padding-top: 38px;
      }}

      main {{
        width: min(100% - 20px, 1180px);
      }}

      .summary-grid, .split, .meta-list, .detail-grid {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>
{body}
</body>
</html>
"""


def _metric_card(label: str, value: str, hint: str) -> str:
    return (
        '<article class="metric">'
        f'<span class="label">{escape(label)}</span>'
        f'<span class="value">{escape(value)}</span>'
        f'<span class="hint">{escape(hint)}</span>'
        "</article>"
    )


def _render_meta_rows(rows: list[tuple[str, str]]) -> str:
    return "\n".join(
        f"<div><dt>{escape(label)}</dt><dd>{escape(value)}</dd></div>"
        for label, value in rows
    )


def _game_link(url: str) -> str:
    if not url:
        return ""
    safe_url = escape(url, quote=True)
    return f'<a class="game-link" href="{safe_url}">Open game on Chess.com</a>'


def _render_moment_card(
    item: Mistake,
    color: str,
    *,
    subtitle: str = "",
) -> str:
    candidate_items = "\n".join(
        f"<li>{escape(candidate.san)} <strong>{escape(candidate.score)}</strong></li>"
        for candidate in item.top_lines[:3]
    )
    subtitle_html = f'<p class="subtitle">{escape(subtitle)}</p>' if subtitle else ""

    return f"""
<article class="moment-card">
  <div class="board-wrap">{_board_svg(item, color)}</div>
  <div class="moment-body">
    <span class="badge {_severity_class(item.severity)}">{escape(item.severity)}</span>
    <h3>{escape(item.move_label)} in the {escape(item.phase.lower())}</h3>
    {subtitle_html}
    <div class="move-line">
      <div class="move-pill">Played <strong>{escape(item.played)}</strong></div>
      <div class="move-pill">Best <strong>{escape(item.best)}</strong></div>
    </div>
    <div class="detail-grid">
      <div><span>Expected loss</span><strong>{item.expected_points_loss:.2f}</strong></div>
      <div><span>Eval swing</span><strong>{item.cp_loss} cp</strong></div>
      <div><span>Scores</span><strong>{escape(item.best_score)} to {escape(item.played_score)}</strong></div>
    </div>
    <p class="note">{escape(item.note)}</p>
    <ul class="candidate-list">{candidate_items}</ul>
  </div>
</article>
"""


def _board_svg(item: Mistake, color: str) -> str:
    board = chess.Board(item.fen)
    best_move = chess.Move.from_uci(item.best_uci)
    played_move = chess.Move.from_uci(item.played_uci)
    orientation = chess.WHITE if color == "White" else chess.BLACK
    arrows = [
        chess.svg.Arrow(best_move.from_square, best_move.to_square, color="#2f8a4b"),
        chess.svg.Arrow(played_move.from_square, played_move.to_square, color="#c2412d"),
    ]
    return chess.svg.board(
        board,
        arrows=arrows,
        coordinates=True,
        orientation=orientation,
        size=420,
    )


def _severity_class(severity: str) -> str:
    return severity.lower().replace(" ", "-")


def _score_to_numeric(score: chess.engine.Score) -> int:
    return score.score(mate_score=MATE_SCORE)


def _format_score(score: chess.engine.Score) -> str:
    mate = score.mate()
    if mate is not None:
        return f"#{mate}"
    centipawns = score.score()
    assert centipawns is not None
    return f"{centipawns / 100:+.2f}"


def _classify_severity(
    best_score: chess.engine.Score,
    played_score: chess.engine.Score,
    expected_points_loss: float,
    player_rating: int | None,
) -> str | None:
    best_ep = _expected_points(best_score, player_rating)
    played_ep = _expected_points(played_score, player_rating)

    if _is_miss(best_ep, played_ep, expected_points_loss):
        return "Miss"
    if expected_points_loss >= 0.20:
        return "Blunder"
    if expected_points_loss >= 0.10:
        return "Mistake"
    if expected_points_loss >= 0.05:
        return "Inaccuracy"
    return None


def _expected_points_loss(
    best_score: chess.engine.Score,
    played_score: chess.engine.Score,
    player_rating: int | None,
) -> float:
    return max(
        0.0,
        _expected_points(best_score, player_rating)
        - _expected_points(played_score, player_rating),
    )


def _expected_points(score: chess.engine.Score, player_rating: int | None) -> float:
    mate = score.mate()
    if mate is not None:
        return 1.0 if mate > 0 else 0.0

    centipawns = score.score(mate_score=MATE_SCORE)
    if centipawns is None:
        return 0.5

    scale = _expected_points_scale(player_rating)
    return 1.0 / (1.0 + exp(-centipawns / scale))


def _expected_points_scale(player_rating: int | None) -> float:
    rating = player_rating if player_rating is not None else 1200
    return max(120.0, min(260.0, 260.0 - (rating * 0.06)))


def _is_miss(
    best_ep: float,
    played_ep: float,
    expected_points_loss: float,
) -> bool:
    return best_ep >= 0.74 and played_ep <= 0.70 and expected_points_loss >= 0.10


def _resolve_threads(threads: int) -> int:
    if threads < 0:
        raise ValueError("--threads must be 0 or greater.")
    if threads > 0:
        return threads
    return os.cpu_count() or 1


def _format_opening(headers: chess.pgn.Headers) -> str:
    eco = headers.get("ECO", "").strip()
    opening = headers.get("Opening", "").strip()
    if opening and not _is_eco_code(opening):
        return _append_eco(opening, eco)

    eco_url_name = _opening_name_from_eco_url(headers.get("ECOUrl", ""))
    if eco_url_name:
        return _append_eco(eco_url_name, eco)

    return f"ECO {eco}" if eco else "Unknown"


def _append_eco(opening: str, eco: str) -> str:
    if not eco or eco in opening:
        return opening
    return f"{opening} ({eco})"


def _is_eco_code(value: str) -> bool:
    return bool(re.fullmatch(r"[A-E]\d{2}", value.strip(), flags=re.IGNORECASE))


def _opening_name_from_eco_url(eco_url: str) -> str:
    if not eco_url:
        return ""

    slug = unquote(urlparse(eco_url).path.rstrip("/").split("/")[-1])
    if not slug:
        return ""

    tokens = [token for token in slug.split("-") if token]
    name_tokens: list[str] = []
    for token in tokens:
        if re.match(r"^\d+\.", token):
            break
        name_tokens.append(token)

    words = [_normalize_opening_word(token) for token in name_tokens]
    segments = _opening_segments(words)
    if not segments:
        return ""
    if len(segments) == 1:
        return segments[0]
    return f"{segments[0]}: {', '.join(segments[1:])}"


def _normalize_opening_word(word: str) -> str:
    replacements = {
        "Queens": "Queen's",
        "Kings": "King's",
    }
    return replacements.get(word, word)


def _opening_segments(words: list[str]) -> list[str]:
    segment_enders = {
        "Attack",
        "Countergambit",
        "Defense",
        "Defence",
        "Gambit",
        "Game",
        "Opening",
        "System",
        "Variation",
    }
    segments: list[str] = []
    current: list[str] = []

    for word in words:
        current.append(word)
        if word in segment_enders:
            segments.append(" ".join(current))
            current = []

    if current:
        if segments:
            segments[-1] = f"{segments[-1]} {' '.join(current)}"
        else:
            segments.append(" ".join(current))

    return segments


def _accuracy_rating(cp_losses: list[int]) -> float:
    if not cp_losses:
        return 0.0
    return mean(_move_accuracy(cp_loss) for cp_loss in cp_losses)


def _move_accuracy(cp_loss: int) -> float:
    return max(0.0, min(100.0, 100.0 * exp(-cp_loss / 125.0)))


def _accuracy_label(accuracy_rating: float) -> str:
    if accuracy_rating >= 95:
        return "Excellent"
    if accuracy_rating >= 85:
        return "Strong"
    if accuracy_rating >= 70:
        return "Solid"
    if accuracy_rating >= 55:
        return "Shaky"
    return "Rough"


def _severity_rank(severity: str) -> int:
    return {"Inaccuracy": 1, "Mistake": 2, "Miss": 3, "Blunder": 4}[severity]


def _move_label(board: chess.Board, san: str) -> str:
    if board.turn == chess.WHITE:
        return f"{board.fullmove_number}. {san}"
    return f"{board.fullmove_number}... {san}"


def _phase_name(board: chess.Board) -> str:
    piece_count = len(board.piece_map())
    if board.fullmove_number <= 10:
        return "Opening"
    if piece_count <= 12:
        return "Endgame"
    return "Middlegame"


def _mistake_note(
    board: chess.Board,
    played_move: chess.Move,
    best_move: chess.Move,
    cp_loss: int,
    severity: str,
) -> str:
    if severity == "Miss":
        return "You missed a chance to move into or keep a clearly better position."
    if board.is_capture(best_move) and not board.is_capture(played_move):
        return "You passed on a forcing capture that Stockfish preferred."
    if board.gives_check(best_move) and not board.gives_check(played_move):
        return "You missed a direct forcing move with check."
    if played_move == chess.Move.from_uci("e1g1") or played_move == chess.Move.from_uci("e8g8"):
        return "Castling was playable, but the engine preferred a more urgent move first."
    if _is_king_side_pawn_push(board, played_move):
        return "This move loosened squares around your king more than the position allowed."
    if _phase_name(board) == "Opening":
        return "This opening choice gave away the initiative early."
    if _phase_name(board) == "Endgame":
        return "The endgame demanded more precision than this move provided."
    if cp_loss >= 150:
        return "This move appears to change the game in a major way."
    return "This move drifted from the best continuation and cost practical chances."


def _is_king_side_pawn_push(board: chess.Board, move: chess.Move) -> bool:
    piece = board.piece_at(move.from_square)
    if piece is None or piece.piece_type != chess.PAWN:
        return False

    from_file = chess.square_file(move.from_square)
    if board.turn == chess.WHITE:
        return from_file in (5, 6, 7)
    return from_file in (5, 6, 7)


def _normalize_result(raw_result: str) -> str:
    mapping = {
        "win": "Win",
        "agreed": "Draw",
        "repetition": "Draw",
        "stalemate": "Draw",
        "timevsinsufficient": "Draw",
        "insufficient": "Draw",
        "50move": "Draw",
        "abandoned": "Loss",
        "checkmated": "Loss",
        "resigned": "Loss",
        "timeout": "Loss",
        "lose": "Loss",
    }
    return mapping.get(raw_result, raw_result.title() if raw_result else "Unknown")


def _parse_rating(raw_rating: str) -> int | None:
    try:
        return int(raw_rating)
    except ValueError:
        return None


def _format_timestamp(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, tz=UTC).astimezone().strftime(
        "%Y-%m-%d %H:%M:%S %Z"
    )


def _build_takeaway(top_mistakes: list[Mistake]) -> str:
    if not top_mistakes:
        return "This game did not contain large engine-defined swings at the chosen depth. Increase depth or review the full move list for smaller inaccuracies."

    opening_count = sum(1 for item in top_mistakes if item.phase == "Opening")
    endgame_count = sum(1 for item in top_mistakes if item.phase == "Endgame")

    if opening_count >= 2:
        return "Your biggest losses came early. Focus on understanding the plans in this opening rather than memorizing moves alone."
    if endgame_count >= 2:
        return "The game was decided late. Endgame precision was the main leak, so review the final conversion or defense phase carefully."
    if any(item.severity == "Miss" for item in top_mistakes):
        return "The biggest pattern was missed conversion chances. When you get an advantage, pause to look for the forcing move that keeps it."
    if any("forcing" in item.note.lower() for item in top_mistakes):
        return "You missed forcing ideas in critical positions. Spend time checking candidate captures and checks before choosing a move."
    return "The main pattern was calculation drift in sharp positions. Slow down at turning points and compare your move against at least one forcing alternative."


def _build_recurring_lessons(reports: list[GameReport]) -> list[str]:
    serious_moves = [
        item
        for report in reports
        for item in report.flagged_moves
        if item.severity != "Inaccuracy"
    ]
    if not serious_moves:
        return [
            "No recurring serious issue was detected. Review the listed inaccuracies for smaller technique improvements."
        ]

    pattern_counts = Counter(_lesson_key(item) for item in serious_moves)
    total = len(serious_moves)
    lessons = [
        _lesson_text(key, count, total)
        for key, count in pattern_counts.most_common()
        if count >= 2 or len(reports) <= 2
    ]

    if len(lessons) < 3:
        average_accuracy = mean(report.accuracy_rating for report in reports)
        if average_accuracy < 75:
            lessons.append(
                "Accuracy is consistently below the solid range. Use a slower review pass after each game and write down the first move where your plan changed."
            )
        else:
            lessons.append(
                "The most useful review habit is to replay only the serious flagged moments and solve each one before revealing the engine move."
            )

    return lessons[:3]


def _lesson_key(item: Mistake) -> str:
    note = item.note.lower()
    if item.severity == "Miss":
        return "missed_conversion"
    if "capture" in note or "check" in note or "forcing" in note:
        return "forcing_scan"
    if "king" in note:
        return "king_safety"
    if item.phase == "Opening":
        return "opening"
    if item.phase == "Endgame":
        return "endgame"
    return "calculation"


def _lesson_text(key: str, count: int, total: int) -> str:
    evidence = f"{count} of {total} serious flag{_plural(total)}"
    lesson_map = {
        "missed_conversion": (
            f"Missed conversion chances recurred ({evidence}). "
            "When you are better, pause for candidate checks, captures, and threats before choosing a quiet move."
        ),
        "forcing_scan": (
            f"Forcing-move blindness showed up repeatedly ({evidence}). "
            "Before committing, do a short scan of checks, captures, and direct threats."
        ),
        "king_safety": (
            f"King-safety concessions recurred ({evidence}). "
            "Treat pawn moves near your king as candidate weaknesses, especially before the endgame."
        ),
        "opening": (
            f"Opening decisions created repeated problems ({evidence}). "
            "Review the first 10 moves and learn the plans behind the opening, not just the move order."
        ),
        "endgame": (
            f"Endgame precision was a recurring leak ({evidence}). "
            "Convert the flagged positions into practice FENs and solve them without the engine first."
        ),
        "calculation": (
            f"Calculation drift was the main theme ({evidence}). "
            "At turning points, compare your intended move with at least one forcing alternative."
        ),
    }
    return lesson_map[key]


def _plural(count: int) -> str:
    return "" if count == 1 else "s"
