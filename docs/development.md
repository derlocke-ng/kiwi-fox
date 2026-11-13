# Development

This page is for people who work on kiwi-fox itself: how to run it from a
checkout, which tests exist and where they run, and how a release is made.

## Run it from a checkout

kiwi-fox imports kiwi-proxy for everything on the network side, so it needs a
kiwi-proxy checkout next to it:

```bash
git clone https://github.com/derlocke-ng/kiwi-proxy
git clone https://github.com/derlocke-ng/kiwi-fox
cd kiwi-fox
make setup          # a .venv with pydantic, pytest and ruff
make run ARGS=list  # the command line, the same as `kiwi-fox list`
make gui            # the app
```

`make setup` creates the virtual environment with the system's site packages,
because PyGObject for the app comes from the distribution. The Makefile looks
for kiwi-proxy in `../kiwi-proxy/src`. Set `KIWI_PROXY_SRC` to use another
place.

## Tests

| Command | What it runs |
|---|---|
| `make test` | The unit tests in `tests/unit`. They need kiwi-proxy (see above) but no Podman and no network. |
| `make lint` | `ruff check` and `ruff format --check` over the sources, tests, container files and tools. |
| `make smoke` | Builds the browser image as `kiwi-fox/browser:smoke` and checks from inside that it has what the Containerfile installs (`tests/smoke/browser-image.sh`). |
| `make leak ARGS="--profile work"` | The leak tests in `tests/leak`. They probe a profile that is running, so start one first. |
| `make screenshots` | Renders the screenshots in `data/screenshots` from the app, under Xvfb. |

## Continuous integration

`.github/workflows/ci.yml` runs on every push and pull request. Each job checks
out kiwi-proxy at its newest release tag, because that is what `kiwi` installs
next to kiwi-fox.

| Job | Where | What |
|---|---|---|
| `test` | GitHub Actions, `ubuntu-latest`, Python 3.12 | The linter, `bash -n install.sh`, and every unit test except the app's windows |
| `gui` | GitHub Actions, Ubuntu 24.04 | The app's windows (`tests/unit/test_ui.py`) with GTK 4 and libadwaita from Ubuntu, under Xvfb |
| `browser-image` | GitHub Actions, `ubuntu-latest` with Podman | The browser image, built without a cache, then checked from inside |

The leak tests are not run in CI, because they need a running profile with its
gateway.

## Releases

A release is a signed tag. `kiwi` installs an app's newest version tag, so the
tag is the release. A maintainer makes and signs it; CI holds no key:

```bash
git tag -s v0.13.0 -m v0.13.0
git push origin v0.13.0
```

For a pushed `v*` tag, `.github/workflows/release.yml` checks that the tag is
annotated, signed by a key in `.github/allowed_signers`, equal to `VERSION` in
`kiwi.manifest` and newer than every other release. It then publishes the
GitHub release with the matching section of `CHANGELOG.md` as its notes.

Before you tag, the version must be the same in `kiwi.manifest`,
`pyproject.toml` and `src/kiwi_fox/__init__.py`; `tests/unit/test_release.py`
checks this. The docs in this folder reach
[kiwi-network.eu](https://kiwi-network.eu/docs/clients/kiwi-fox/) with the
next release tag, so run the docs checker before you tag:

```bash
python3 .claude/skills/kiwi-docs/scripts/check-docs.py .
```
