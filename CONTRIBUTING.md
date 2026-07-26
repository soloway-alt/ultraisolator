# Contributing

Thanks for your interest in Esports Isolator PRO.

This project changes Windows process scheduling behavior, so contributions need to be small, testable, and explicit about safety impact.

## Getting started

```powershell
git clone https://github.com/chezzof/ultraisolator.git
cd ultraisolator
python -m pip install -r requirements.txt -r requirements-dev.txt
copy config.json.example config.json
python -m unittest discover -s tests -p "test_*.py" -v
ruff check .
mypy
npm --prefix ui install
npm --prefix ui run build:renderer
npm --prefix ui run smoke
npm --prefix ui run lint
npm --prefix ui run test:unit
```

## Development workflow

1. Create a branch from `main`.
2. Make changes with the smallest useful diff.
3. Write or update tests for behavior changes.
4. Run the relevant verification commands before opening a PR.
5. Avoid new dependencies unless they are necessary and documented.
6. Document any Windows privilege, anti-cheat, registry, power-plan, or process-tuning behavior change.

## Pull request checklist

- Explain the user-visible behavior change.
- Include Windows version, Python version, and game/test context when relevant.
- Run `python -m unittest discover -s tests -p "test_*.py" -v`, `ruff check .`, and `mypy`.
- For UI changes, run `npm --prefix ui run build:renderer`, `npm --prefix ui run smoke`, `npm --prefix ui run lint`, `npm --prefix ui run lint:css`, and `npm --prefix ui run test:unit`; for renderer-visible changes also `npm --prefix ui run test:ui-quality`.
- For packaging changes, run `npm --prefix ui run build` or explain why local packaging was not available.
- Keep refactors focused and separate from behavior changes.

## Reporting issues

- Describe your Windows version, Python version, and game.
- Mention whether you ran as Administrator.
- Mention whether `enable_background_jailing` was enabled.
- Include the relevant portion of your log (`--log-file isolator-run.log`).
- Never paste your `config.json` if it contains custom paths; use `config.json.example` as a template.

## Benchmark contributions

Benchmark reports are useful only when the context is clear:

- Name the game, map/workload, resolution, graphics settings, CPU, GPU, RAM, and Windows build.
- Include whether overlays, recording, Discord, browsers, or launchers were running.
- Use before/after runs with the same workload.
- Keep anti-cheat notes factual; do not recommend bypasses or unsafe workarounds.

## Code of conduct

Be respectful. We are here to make games smoother, not to argue. By
participating you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).
