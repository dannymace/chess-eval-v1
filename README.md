# Chess Eval V1

Minimal Dockerized CLI that:

- takes a Chess.com username
- fetches the latest finished public game from Chess.com
- analyzes that game locally with Stockfish
- prints a short coaching-style report

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
docker run --rm chess-eval-v1 hikaru --depth 12 --threads 2 --hash-mb 256 --max-mistakes 5
```

## Notes

- Chess.com PubAPI is public and read-only. Recent games can lag because the API is cached upstream.
- V1 focuses on your moves only, not your opponent's moves.
- The report is intended to surface the biggest practical errors and one main coaching takeaway.
