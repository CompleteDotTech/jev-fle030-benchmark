"""Coverage-aware reporting; interrupted or smoke runs never become benchmark scores."""
from __future__ import annotations
import json
import statistics
from pathlib import Path
from . import TASKS
from .util import atomic_json, load_events


def compile_report(root: Path) -> dict:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    config = manifest["config"]
    rows, events, summaries = [], [], []
    for job in manifest["jobs"]:
        folder = root / "episodes" / job["id"]
        path = folder / "summary.json"
        summary = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
            "status": "not_started", "success": None, "steps": 0}
        # Check identity rather than trusting a copied summary from another episode.
        if path.exists() and (summary.get("task"), summary.get("attempt"), summary.get("policy")) != (
                job["task"], job["attempt"], config["policy"]):
            raise ValueError(f"Episode identity mismatch: {job['id']}")
        summaries.append((job, summary))
        events.extend(load_events(folder / "events.jsonl"))
    profile_eligible = (config["policy"] in {"jev", "random"} and config["steps"] == 64
                        and config["attempts"] == 8)
    for task in config["tasks"]:
        task_summaries = [s for j, s in summaries if j["task"] == task]
        completed = [s for s in task_summaries if s["status"] == "complete"
                     and isinstance(s.get("success"), bool)
                     and s.get("max_steps") == config["steps"]
                     and (s["success"] or s.get("steps") == config["steps"])]
        successes = sum(s["success"] for s in completed)
        eligible = profile_eligible and len(completed) == 8
        rows.append({"task": task, "planned": config["attempts"], "complete": len(completed),
                     "interrupted": sum(s["status"] == "interrupted" for s in task_summaries),
                     "not_started": sum(s["status"] == "not_started" for s in task_summaries),
                     "native_successes": successes,
                     "empirical_pass_at_8": bool(successes) if eligible else None,
                     "completed_trial_success_rate": successes / len(completed) if completed else None})
    responses = [e for e in events if e["event"] == "api_response"]
    latencies = [e["latency_seconds"] for e in responses if "latency_seconds" in e]
    full_coverage = (set(config["tasks"]) == set(TASKS) and
                     all(row["empirical_pass_at_8"] is not None for row in rows))
    steps = [e for e in events if e["event"] == "step"]
    return {
        "protocol": "Jev typed-action scaffold on native FLE 0.3.0 lab-play",
        "stock_leaderboard_replication": False,
        "policy": config["policy"], "model": manifest.get("model"),
        "is_full_24_task_8_attempt_evaluation": full_coverage,
        "labplay_empirical_pass_at_8": (sum(r["empirical_pass_at_8"] for r in rows) / len(TASKS)
                                         if full_coverage else None),
        "metric_note": "Observed any-success in eight completed attempts, not an unbiased pass@k estimator. "
                       "Smoke, partial coverage and interrupted attempts do not receive an aggregate score. "
                       "Policy-seed changes permute criteria, not the map or provider sampling seed.",
        "tasks": rows,
        "totals": {
            "planned_episodes": len(summaries),
            "complete_episodes": sum(r["complete"] for r in rows),
            "interrupted_episodes": sum(r["interrupted"] for r in rows),
            "not_started_episodes": sum(r["not_started"] for r in rows),
            "recorded_steps": len(steps),
            "steps_with_native_errors": sum(bool(e.get("error_occurred")) for e in steps),
            "recorded_api_attempts_including_retries": sum(e["event"] == "api_attempt" for e in events),
            "validated_api_responses": len(responses),
            "recorded_api_errors": sum(e["event"] == "api_error" for e in events),
            "known_input_tokens": sum(e["response"]["usage"]["input_tokens"] for e in responses),
            "known_output_tokens": sum(e["response"]["usage"]["output_tokens"] for e in responses),
            "api_response_latency_median_seconds": statistics.median(latencies) if latencies else None,
            "api_response_latency_max_seconds": max(latencies) if latencies else None,
            "episode_wall_seconds": sum(s.get("wall_seconds", 0) for _, s in summaries),
        },
        "billing_note": "Token totals include only validated responses; unsuccessful or interrupted requests may "
                        "also be billable. API-call caps are not dollar caps. Reconcile with provider billing.",
        "provenance": {k: manifest.get(k) for k in ("source_fingerprint", "fle", "engine", "config_sha256")},
    }


def write_report(root: Path) -> dict:
    result = compile_report(root)
    atomic_json(root / "report.json", result)
    lines = ["# Jev / FLE 0.3.0 run report", "", f"Policy: `{result['policy']}`", "",
             "Custom typed-action scaffold; not a stock leaderboard replication.", "",
             f"Full 24-task / 8-attempt coverage: **{result['is_full_24_task_8_attempt_evaluation']}**", "",
             "Aggregate empirical Pass@8: " + (str(result["labplay_empirical_pass_at_8"])
                   if result["labplay_empirical_pass_at_8"] is not None else "**not available (incomplete or diagnostic profile)**"), "",
             "| Task | Complete | Interrupted | Not started | Native successes | Empirical Pass@8 |",
             "|---|---:|---:|---:|---:|---|" ]
    for row in result["tasks"]:
        score = "not available" if row["empirical_pass_at_8"] is None else str(row["empirical_pass_at_8"])
        lines.append(f"| {row['task']} | {row['complete']} | {row['interrupted']} | {row['not_started']} | {row['native_successes']} | {score} |")
    lines += ["", result["metric_note"], "", "## Telemetry totals", "", "```json",
              json.dumps(result["totals"], indent=2), "```", "", result["billing_note"], ""]
    (root / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return result
