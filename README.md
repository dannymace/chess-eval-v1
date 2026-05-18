# Chess Eval V1

Minimal Dockerized CLI that:

- takes a Chess.com username
- fetches the latest finished public game from Chess.com
- analyzes that game locally with Stockfish
- prints a short coaching-style report with an opening name, accuracy rating, Chess.com-style move categories, and tactical pattern hints

## Build

```bash
docker build -t chess-eval-v1 .
```

## Run

```bash
docker run --rm chess-eval-v1 hikaru
```

Tune the analysis depth or engine settings:

```bash
docker run --rm chess-eval-v1 hikaru --depth 12 --threads 4 --hash-mb 256 --max-mistakes 5
```

Analyze multiple recent games and surface recurring lessons:

```bash
docker run --rm chess-eval-v1 hikaru --last 20
```

Generate a standalone HTML report with board diagrams:

```bash
mkdir -p reports
docker run --rm -v "$PWD/reports:/reports" chess-eval-v1 hikaru --html /reports/latest.html
```

HTML also works with trend reports. Trend HTML focuses on summary tables and recurring lessons rather than board diagrams:

```bash
docker run --rm -v "$PWD/reports:/reports" chess-eval-v1 hikaru --last 20 --html /reports/trend.html
```

## Notes

- Chess.com PubAPI is public and read-only. Recent games can lag because the API is cached upstream.
- V1 focuses on your moves only, not your opponent's moves.
- `--last N` analyzes the most recent finished public games and produces a trend report instead of a full per-game report.
- `--html PATH` writes a standalone visual report. Single-game reports include chessboards for the biggest moments; trend reports use summary tables.
- Opening names are read from Chess.com PGN headers when available. If Chess.com only provides an ECO code and URL, the app converts the URL slug into a readable name.
- ACPL is average centipawn loss across the analyzed player's moves. In trend reports it is weighted by player move count across games.
- Accuracy is a `0-100` estimate derived from per-move centipawn loss. It is useful for comparing your own games, not as an exact Chess.com accuracy clone.
- Move categories use an approximate expected-points model so missed winning chances are separated as `Miss` instead of being treated as raw centipawn blunders.
- Tactical patterns are conservative heuristics over the board before a flagged move and Stockfish's preferred move.
- The default analysis depth is `11`. The default thread count is `0`, which uses all CPUs visible inside the Docker container.
- The report is intended to surface the biggest practical errors and one main coaching takeaway.
