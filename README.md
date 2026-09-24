# CompleteTech · Jev × FLE 0.3.0

A version-pinned setup and a custom **Jev typed-action harness** for the 24-task
Factorio Learning Environment v0.3.0 lab-play benchmark.

**Status:** the pinned FLE environment, dedicated Factorio server, visible GUI
client, native engine smoke test, and bounded live Jev gameplay smoke test were
validated on 2026-09-24. The four-action Jev trial completed without native task
success. No full 192-trial sweep or aggregate benchmark score is included. See
`docs/validation.md` for the validation boundary.

This is a standalone integration. It does **not** modify, deploy, or benchmark the
existing `CompleteDotTech/jev-factorio-agent` controller. Its action scaffold is
new and deliberately isolated from your ongoing gameplay world.

## What is pinned

| Component | Value |
|---|---|
| FLE release | `0.3.0` |
| FLE Git commit | `714482a6fc3ed3da6b6288c35fb697c458415e31` |
| Jev | `jev-1.13.0` |
| Factorio headless image | `factoriotools/factorio:1.1.110`; resolved to a registry digest on first pull |
| Gym API | `gym==0.26.2`, not Gymnasium |
| A2A SDK compatibility | `a2a-sdk==0.3.26` |
| Scenario | `default_lab_scenario`, one agent, no additional mods, vision disabled |
| Full sweep | 24 tasks × 8 attempts × at most 64 actions = 192 episodes, at most 12,288 actions |

The installer uses the immutable Git commit. Preflight requires its VCS-install
metadata and verifies Git blob hashes for eight critical FLE files. It does not
claim that every transitive dependency is pre-locked: the resolved environment
is recorded after installation and with every run. The preparation session did
not resolve or install those external dependencies.

## Requirements on the execution host

Use an **x86-64** machine with Docker Engine + Compose v2, or Windows Docker
Desktop using Linux containers. Linux or WSL2 is the recommended command path.
Install Git and either Python 3.11/3.12 or `uv`. With `uv`, bootstrap provisions
Python 3.11. Internet access is required for Python/dependencies, GitHub, the
Docker image, and the TypeSafe API. ARM is intentionally rejected by this profile.

No GPU is required on the host for this adapter: it calls the hosted Jev endpoint.
The GUI Factorio client is optional; FLE v0.3.0 supports headless operation. To
watch via a GUI, use a compatible 1.1.110 installation and the appropriate game
license. The benchmark server's local game port is `35197`.

On Windows with a compatible Factorio installation, launch the GUI after
`cluster start` and connect to `127.0.0.1:35197` (Multiplayer → Connect to
address). You can also launch `factorio.exe --mp-connect 127.0.0.1:35197`.
The benchmark resets its disposable world between episodes and pauses between
actions, so expect the view to reload or stop moving during decisions. Observe
only: player actions would change the benchmark state.

A TypeSafe API key is needed only for `api-smoke` and Jev runs. Supply it through
the masked `--prompt-key` prompt or the local `TYPESAFE_API_KEY` environment variable.
Do not put it in configs, command-line arguments, a Git repository, or chat.

## 1. Install the local environment

Extract the ZIP, then enter its `jev-fle030-benchmark` directory:

```bash
python bootstrap.py
```

Bootstrap creates `.venv`, installs the pinned FLE source and this package in
editable mode, runs the offline tests, writes `environment.freeze.txt`, and
checks the actual FLE imports. It does not install Docker, start a game, contact
Jev, or change system Python. It refuses to overwrite an existing virtualenv;
use `--reuse-venv` only after inspecting that environment.

Use this interpreter for all following commands:

```bash
# Linux / WSL2
source .venv/bin/activate

# Windows PowerShell alternative
# .\.venv\Scripts\Activate.ps1

python -m jev_fle doctor
```

For native Windows without shell activation, substitute
`.\.venv\Scripts\python.exe` for `python`. Bootstrap can be run directly from
PowerShell. No dependency install has been tested on Windows in this delivery.

## 2. Start the isolated benchmark world

```bash
python -m jev_fle cluster start
python -m jev_fle doctor --engine
```

The project is **`jev-fle030`**, not the upstream default cluster. It binds only
`127.0.0.1:27100` for RCON and `127.0.0.1:35197` for the game. The upstream RCON
password remains `factorio`; keep the loopback-only binding. Do not expose it on
the network. Compose mounts upstream scenario/config resources and a dedicated
local screenshot directory, not your existing gameplay save.

Initial server startup may not be finished when `cluster start` returns. An
unsuccessful immediate `doctor --engine` is not a benchmark result; inspect the
server log and rerun the check after it is ready:

```bash
docker compose -p jev-fle030 -f .runtime/compose.json logs --tail 100 factorio_0
```

The launcher records the pulled image digest and ID, checks the actual server
version, and verifies the running project's ownership and port bindings before
any benchmark reset. Use the same directory for subsequent commands. No
arbitrary external RCON address or existing gameplay controller is accepted.

## 3. Verify the engine, then the Jev connection

```bash
# Resets only the disposable benchmark world. No model/API calls.
python -m jev_fle engine-smoke --ack-reset --output results/engine-smoke-01

# Exactly one live HTTP attempt; no game reset. This is not a benchmark score.
python -m jev_fle api-smoke --allow-live --prompt-key --output results/api-smoke-01
```

`api-smoke` checks authentication, the pinned resolved model, Choice response
shape, probabilities, and usage fields. It records the selected answer rather
than assuming the model solved the test question. A wrong answer is a model
behavior observation, distinct from an API integration failure.

## 4. Run a bounded Jev gameplay smoke test

```bash
python -m jev_fle run \
  --config configs/smoke.json \
  --output results/jev-smoke-01 \
  --ack-reset --allow-live --prompt-key \
  --max-api-calls 64
```

This executes one attempt of `iron_ore_throughput`, at most four actions. It is an
integration check, **not** a full benchmark. Review `report.md`, episode action
programs, native errors, and the saved receipts before authorizing a full sweep.

Every output directory must be new. Existing results are never overwritten or
silently resumed. To repeat a check, choose a new suffix such as `-02`.

## 5. Full 24-task evaluation

Only after both live smoke tests work:

```bash
python -m jev_fle run \
  --config configs/labplay.json \
  --output results/jev-labplay-01 \
  --ack-reset --allow-live --prompt-key \
  --max-api-calls 50000
```

**Review the call cap before running.** It is a maximum number of HTTP attempts,
including retries, across the entire sweep, not a dollar cap or a prediction of
usage. One game action can require several dependent Jev calls. Provider charges
for failed or interrupted requests may not appear in returned token totals.
Exhausting the budget leaves the sweep explicitly incomplete.

Each episode has a configurable 1,800-second wall deadline in the full profile.
This is an operational safety limit, not an upstream benchmark rule. A deadline,
API failure, protocol mismatch, or infrastructure failure is an interruption,
not a failed completed trial. The sweep stops on the first interrupted episode;
remaining jobs are reported as not started. Native in-game tool errors remain
visible to Jev and do not by themselves abort the episode.

The default eight attempts vary the deterministic **criterion-order seed**.
This is not a game-map seed or a supported Jev sampling seed. See methodology.

An explicit no-model comparator is provided:

```bash
python -m jev_fle run --config configs/random-baseline.json \
  --output results/random-labplay-01 --ack-reset
```

This random policy is never substituted after a Jev error. Its reports are labeled
`random`; it is not a Jev result.

## Outputs and accounting

```text
results/<run>/
  manifest.json                 # model, source/install/image provenance, jobs, config/call cap
  environment.freeze.txt        # installed Python distribution versions
  jobs/<episode>.json           # no credentials
  console/<episode>.log         # worker diagnostics
  episodes/<episode>/
    initial-state.json.gz       # native starting snapshot; SHA256 in receipts
    events.jsonl                # requests, distributions, decisions, code, native observations
    summary.json                # complete/interrupted, native success, steps, usage
  report.json
  report.md
  stop.json                     # present when the sweep stops early
```

Receipts are flushed before sending potentially billable calls. State, options,
answers, action programs, native errors, timing, game ticks, and successful-response
usage are retained. API credentials and HTTP response bodies on failure are not
logged. Serialized Python functions from observations are not evaluated or
unpickled; their count is retained. Text-only observations omit image payloads.

```bash
python -m jev_fle report results/jev-labplay-01
python -m jev_fle cluster stop
```

`cluster stop` affects only `jev-fle030`. Do not use upstream `fle cluster stop`
for this package. A lock prevents concurrent episodes or cluster changes from
sharing this benchmark world. A stale `.runtime/run.lock` after an operating
system crash must be inspected against its PID before manual removal.

## What the Jev adapter does—and does not do

Jev chooses a skill, then typed parameters. Independent questions are batched;
dependent choices see earlier selections. Deterministic code emits only fixed,
allowlisted FLE-tool programs. There are 14 skill categories, including placement,
adjacent placement with separate facing, belts/pipes/pole connections, recipes,
rotation, recovery, bounded transfers, batched refueling, resource lookup, and a
generic steam-power block. No other model is called to generate code or summarize
history. The last five decisions provide explicit local history.

This is a **starter action scaffold**, not a demonstrated strong Factorio policy.
Only basic inventory/reference preconditions are filtered; FLE still validates
placement, transfer contents, power/fluid connection feasibility, and recipes.
The projection keeps at most 40 parseable name/position entity references and
reports omissions. Composite belt/pipe groups are not fully modeled. There is
no complete spatial planner, recipe-dependency solver, paged entity selection,
craft/research skill tree, or support for multiplayer/open-world evaluation.
Those choices can materially limit results, especially on advanced tasks.

Consequently, this package measures **Jev plus this particular scaffold on native
FLE tasks**, not unassisted Jev, not the existing gameplay controller, and not a
stock code-generating-agent leaderboard replication. The generic steam-power
macro adapts the public FLE release example; no full-task solutions or benchmark
trajectories are bundled. Report that prior scaffolding when publishing results.

See [methodology](docs/methodology.md), [source references](docs/sources.md), and
[validation](docs/validation.json).
