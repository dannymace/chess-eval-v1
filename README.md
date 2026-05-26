# Chess Eval V1

Minimal Dockerized CLI that:

- takes a Chess.com username
- fetches the latest finished public game from Chess.com
- analyzes that game locally with Stockfish
- prints a short coaching-style report with an opening name, accuracy rating, Chess.com-style move categories, best-move highlights, and tactical pattern hints

Current release: `1.0.1`

## Build

```bash
docker build -t chess-eval-v1 .
```

Or download the release image tarball from the GitHub release and load it:

```bash
docker load -i chess-eval-v1-1.0.1-image.tar.gz
```

## Run

The easiest path is to use the included wrapper for your platform. The wrappers do not rely on bind mounts; they run the container, copy `/reports` back to this repo's `reports/` folder, and remove the container.

Windows PowerShell:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 hikaru
```

Windows `cmd.exe`:

```cmd
run.cmd hikaru
```

WSL, Linux, and macOS:

```bash
./run.sh hikaru
```

You do not need to pass `--html` or remember Docker mount syntax.

If you run raw Docker instead of a wrapper, mount `/reports`; Docker cannot copy files back to the host by itself:

```bash
mkdir -p reports
docker run --rm -v "$PWD/reports:/reports" chess-eval-v1 hikaru
```

PowerShell raw Docker from a WSL path:

```powershell
$out = Join-Path (Get-Location).ProviderPath 'reports'
New-Item -ItemType Directory -Force -Path $out | Out-Null
docker run --rm -v "${out}:/reports" chess-eval-v1 hikaru
```

Single-game reports are named from the game date, opponent, and Chess.com game id, for example `2026-05-04_sakke1989_943998639.html`.

Tune the analysis depth or engine settings:

```bash
./run.sh hikaru --depth 12 --threads 4 --hash-mb 256 --max-mistakes 5
```

Analyze multiple recent games and surface recurring lessons:

```bash
./run.sh hikaru --last 20
```

Trend reports are named from the latest game date and username, for example `2026-05-04_hikaru_last-20.html`.

Override the HTML output path:

```bash
docker run --rm -v "$PWD/reports:/reports" chess-eval-v1 hikaru --html /reports/latest.html
```

HTML also works with trend reports. Trend HTML includes summary tables, recurring lessons, and board diagrams for detected tactical misses:

```bash
docker run --rm -v "$PWD/reports:/reports" chess-eval-v1 hikaru --last 20 --html /reports/trend.html
```

Check the installed version:

```bash
docker run --rm chess-eval-v1 --version
```

## Notes

- Chess.com PubAPI is public and read-only. Recent games can lag because the API is cached upstream.
- V1 focuses on your moves only, not your opponent's moves.
- `--last N` analyzes the most recent finished public games and produces a trend report instead of a full per-game report.
- HTML is created on every run. `--html PATH` overrides the automatic path. Single-game reports include chessboards for the biggest moments, your three best moves, and detected tactics; trend reports include summary tables plus board examples for strong moves and tactical misses.
- Opening names are read from Chess.com PGN headers when available. If Chess.com only provides an ECO code and URL, the app converts the URL slug into a readable name.
- ACPL is average centipawn loss across the analyzed player's moves. In trend reports it is weighted by player move count across games.
- Accuracy is a `0-100` estimate derived from per-move centipawn loss. It is useful for comparing your own games, not as an exact Chess.com accuracy clone.
- Move categories use an approximate expected-points model so missed winning chances are separated as `Miss` instead of being treated as raw centipawn blunders.
- Tactical patterns are conservative heuristics over the board before a flagged move and Stockfish's preferred move.
- The default analysis depth is `11`. The default thread count is `0`, which uses all CPUs visible inside the Docker container.
- The report is intended to surface the biggest practical errors and one main coaching takeaway.
