# Mythfall

An open-ended fantasy RPG for PocketRealms: a persistent world, bounded simulation
time, DM adjudication, actor-limited NPC minds, shared effects, party combat and
character panels. Python rules and seed assets live in `mythfall/`; PWA game
panels and their single world controller live in `client/`.

This repository publishes independently through `pocketrealms deploy .`.
`pocketrealms.json` declares the workspace capability and coordinates one wheel
and panel bundle. Each game session retains its dedicated editable workspace.
Changing the publication resets prior worlds during pre-alpha; reconnecting or
replacing a pod on the same release preserves game state and edits.

## Build and test

Use Python 3.12, Node 22 and Docker. `platform.lock.json` pins the public CLI,
panel builder, compiled browser test host and private RealmEngine image digest.
No PocketRealms checkout or Atlas source is required.

```sh
npm ci --ignore-scripts
python tools/install-platform.py
python -m pip install setuptools==80.9.0 wheel==0.45.1
SOURCE_DATE_EPOCH=315532800 python -m pip wheel --no-deps --no-build-isolation --wheel-dir server .
python tests/verify_wheel.py server
node .platform/ui/node_modules/@pocketrealms/module-ui/build-module-ui.mjs --entry client/entry.jsx --out-dir build/client
npm test
pocketrealms validate .
```

The [CI workflow](.github/workflows/deploy.yml) shows wheel tests and real
desktop/mobile Atlas evaluation against those pinned artifacts. Its image reader
has only Artifact Registry read access; game tests receive no cloud credentials.
A separate `POCKETREALMS_API_KEY` secret is restricted to this module and the
read/deploy scopes. Provider credentials remain in Model Gateway.

See [evaluation instructions](evaluation/README.md), [game rules](RULES.md), and
the [workspace contract](https://github.com/SquareRoundCurly/PocketRealms/blob/main/Publishing/workspace-contract.md).
