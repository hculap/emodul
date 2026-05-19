# Contributing

Thanks for considering a contribution! This project is small and pragmatic —
issues, PRs, and ideas are welcome.

## Quick start (dev setup)

```bash
git clone https://github.com/hculap/emodul.git
cd emodul
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/emodul --help
```

## Before opening a PR

- **Match the existing style.** Small files, immutable patterns, no
  unnecessary abstractions.
- **No tests required for trivial changes** but if you touch HTTP/API
  shapes please verify against your own eModul account.
- **Don't commit secrets.** `~/.config/emodul/config.json`, any JWT, the
  `benchamr/` dump, anything in `probes/` — all are `.gitignore`d, keep
  it that way.
- **Squash before merge.** One feature = one commit.

## Architecture overview

- `emodul/api.py` — every endpoint is a method on `ApiClient`. Add new
  endpoints here first.
- `emodul/commands/*.py` — one click subcommand group per file.
- `emodul/settings_map.py` — named-slug settings inventory; add new
  controller parameters here.
- `emodul/storage.py` — SQLite schema for the watcher; bump cautiously
  (no migrations framework yet).

See [README.md § Architecture](README.md#architecture) for full layout.

## Reporting bugs

Use the bug-report issue template. Include:
- `emodul --version`
- Controller model (visible via `emodul --json modules list`)
- Exact command + `--json` output
- Stderr (API errors print there)

**Do not paste your JWT, `user_id`, `udid` or controller name** in public
issues — anonymise first.

## Adding support for a new controller

The CLI is tested on **L-4X WIFI** but the API surface is shared across
most Tech controllers (L-8, L-9, L-12, etc.). If your controller exposes
endpoints we don't wrap:

1. Find the call in your browser DevTools (F12 → Network → XHR on
   emodul.pl).
2. Replicate via `emodul raw <METHOD> <path>` first.
3. Once confirmed, add the method to `emodul/api.py` and a wrapping
   command to `emodul/commands/`.
4. If the parameter belongs to a menu, add a friendly slug in
   `emodul/settings_map.py`.

## Recording a demo

```bash
brew install asciinema     # macOS
# OR
apt install asciinema      # Ubuntu

asciinema rec demo.cast
# ... run a few emodul commands ...
# Ctrl-D to stop

# Upload (optional):
asciinema upload demo.cast
```

For animated GIF use [`agg`](https://github.com/asciinema/agg):

```bash
agg demo.cast demo.gif
```

## Code of conduct

This project follows the
[Contributor Covenant v2.1](CODE_OF_CONDUCT.md). Be kind.
