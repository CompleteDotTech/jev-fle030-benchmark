# Benchmark protocol and interpretation

## Target and limits

The target is the v0.3.0 single-agent lab-play suite, not open-world or multiagent
Factorio. Its 24 task definitions specify 64 actions per trajectory. Most quotas
are 16 target items per 60 game seconds; selected fluids require 250. Exact task
IDs, including upstream `sufuric_acid_throughput`, are preserved.

The runner calls FLE's own task factory and `FactorioGymEnv.step(Action(...))`.
It restores each task's native starting GameState and does not insert extra
inventory, alter recipes or quotas, skip verification, backtrack unsuccessful
actions, or terminate using its own substitute score. Native verification and
termination must agree. The custom runner owns the 64-action maximum because
the bare v0.3.0 Gym environment does not enforce that trajectory length itself.

## Two important source-versus-description distinctions

The release description discusses throughput during a holdout period. In the
actual pinned `ThroughputTask.verify` implementation, the configured pre-holdout
sleep is commented out. It repeatedly measures 60-game-second windows while the
achieved throughput strictly increases, retaining the maximum. The adapter does
not "fix" this: doing so would change the benchmark being measured. A stricter
steady-state protocol should be published under a separate name.

`FactorioGymEnv.reset(seed=...)` explicitly does not use its seed argument. This
runner does not pass one. Its `policy_seed` only permutes candidate ordering and
seeds the explicit random comparator. It is neither a map-generation seed nor a
provider-side model seed. Snapshots and hashes are saved, but identical terrain or
independent sampled attempts must not be asserted without further verification.

## Jev-specific experimental treatment

The stock example agent emits Python; Jev instead returns typed decisions. The
experimental treatment here is the complete 14-skill candidate compiler,
observation projection, five-decision history, fixed model version, and criterion
order scheme. Every response distribution and emitted program is retained.
This is not the existing `jev-factorio-agent` repository's controller.

The generic steam-power skill is adapted from the FLE release's public teaching
example. It is explicit human-provided scaffolding. There are no hidden target-
specific complete solutions, retrieved benchmark trajectories, or teacher-model
calls. Report this distinction, rather than labeling the result "raw Jev".

An FLE action can contain several tool operations and several preceding Jev calls.
Therefore both **action count** and **HTTP attempts/token usage/wall time** must be
reported. Macro versus primitive granularity prevents simple cost-free
comparisons on action count alone. The explicit random comparator controls for
this same action scaffold, but not for every possible source of variation.

## Metrics and missing data

A trial is successful only on native FLE verification. A completed unsuccessful
trial must use its full action budget. Early API errors, wrong response schemas,
hard timeouts, startup failures, and user interruption have unknown benchmark
outcomes. They are not counted as ordinary failures or replaced with random play.

The report exposes per-task observed any-success in eight completed 64-action-
budget trials as **empirical Pass@8**. It is not the unbiased pass@k estimator
from a larger pool, and it does not prove eight independent model samples.
There is no aggregate score unless all 24 tasks have all eight completed trials
under the full action-budget profile. Smoke and partial runs have null aggregate
metrics. Conditional success rates among completed trials are labeled as such;
selection bias remains possible when other trials are interrupted.

Eight attempts are insufficient for narrow confidence intervals on many rates.
Do not infer statistical superiority from a single small sweep. Matched-protocol
replications and uncertainty analysis are separate work.

## Operational deviations and known limitations

Episodes run serially against a disposable server, guarded by an exclusive lock.
The initial snapshot is restored before an attempt, and the world is paused
between decisions. An outer subprocess wall deadline protects against a native
verification loop or server call that never returns. That deadline is not part
of the stock benchmark; timed-out trials are explicitly interrupted.

The entity projection caps parseable entity references at 40. It does not model
composite groups or all spatial/fluid constraints. The policy offers general
recipes with only partial machine filtering. Error feedback can help recovery,
but no success on any real task was demonstrated during preparation.

No live run, provider-cost total, throughput result, or leaderboard placement is
included in the package. Tests use synthetic fixtures and validate mechanics,
not Factorio-playing competence.
