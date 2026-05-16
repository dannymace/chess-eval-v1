from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import UTC, datetime
from math import exp
from statistics import mean

import chess
import chess.engine
import chess.pgn

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
    best: str
    best_score: str
    played_score: str
    cp_loss: int
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
    total_player_moves: int
    accuracy_rating: float
    accuracy_label: str
    average_cp_loss: float
    inaccuracies: int
    mistakes: int
    blunders: int
    top_mistakes: list[Mistake]
    takeaway: str


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
    elif black_name.lower() == username.lower():
        player_color = chess.BLACK
        color_name = "Black"
        player_result = latest_game.game.get("black", {}).get("result", "")
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

    with chess.engine.SimpleEngine.popen_uci(engine_path) as engine:
        engine.configure(
            {
                "Threads": threads,
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

                severity = _classify_severity(best_score, played_score, cp_loss)
                if severity is not None:
                    mistakes.append(
                        Mistake(
                            move_label=_move_label(board, san),
                            phase=_phase_name(board),
                            played=san,
                            best=best_san,
                            best_score=_format_score(best_score),
                            played_score=_format_score(played_score),
                            cp_loss=cp_loss,
                            severity=severity,
                            note=_mistake_note(board, move, best_move, cp_loss),
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
        key=lambda item: (item.cp_loss, _severity_rank(item.severity)),
        reverse=True,
    )
    top_mistakes = sorted_mistakes[:max_mistakes]
    accuracy_rating = _accuracy_rating(cp_losses)

    return GameReport(
        username=username,
        color=color_name,
        result=_normalize_result(player_result),
        opening=game.headers.get("Opening") or game.headers.get("ECO") or "Unknown",
        time_class=str(latest_game.game.get("time_class", "unknown")),
        url=str(latest_game.game.get("url", "")),
        end_time=_format_timestamp(int(latest_game.game["end_time"])),
        total_player_moves=player_moves,
        accuracy_rating=accuracy_rating,
        accuracy_label=_accuracy_label(accuracy_rating),
        average_cp_loss=mean(cp_losses) if cp_losses else 0.0,
        inaccuracies=sum(1 for item in mistakes if item.severity == "Inaccuracy"),
        mistakes=sum(1 for item in mistakes if item.severity == "Mistake"),
        blunders=sum(1 for item in mistakes if item.severity == "Blunder"),
        top_mistakes=top_mistakes,
        takeaway=_build_takeaway(top_mistakes),
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
                    f"  Eval swing: {item.cp_loss} cp. Best line {item.best_score}; played line {item.played_score}.",
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
    cp_loss: int,
) -> str | None:
    best_mate = best_score.mate()
    played_mate = played_score.mate()

    if best_mate is not None and (played_mate is None or abs(played_mate) > abs(best_mate)):
        return "Blunder"
    if cp_loss >= 150:
        return "Blunder"
    if cp_loss >= 60:
        return "Mistake"
    if cp_loss >= 20:
        return "Inaccuracy"
    return None


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
    return {"Inaccuracy": 1, "Mistake": 2, "Blunder": 3}[severity]


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
) -> str:
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
    if any("forcing" in item.note.lower() for item in top_mistakes):
        return "You missed forcing ideas in critical positions. Spend time checking candidate captures and checks before choosing a move."
    return "The main pattern was calculation drift in sharp positions. Slow down at turning points and compare your move against at least one forcing alternative."
