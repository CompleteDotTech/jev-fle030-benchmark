# Primary sources inspected

Accessed during preparation on 2026-09-24. Release source is pinned independently
of the current main branch. No PDF source was used for implementation.

- FLE v0.3.0 release, examples, and evaluation description:
  https://jackhopkins.github.io/factorio-learning-environment/versions/0.3.0.html
- Exact Git release ref:
  https://github.com/JackHopkins/factorio-learning-environment/tree/714482a6fc3ed3da6b6288c35fb697c458415e31
- Environment step/reset and observation contract:
  https://github.com/JackHopkins/factorio-learning-environment/blob/v0.3.0/fle/env/gym_env/environment.py
  https://github.com/JackHopkins/factorio-learning-environment/blob/v0.3.0/fle/env/gym_env/action.py
  https://github.com/JackHopkins/factorio-learning-environment/blob/v0.3.0/fle/env/gym_env/observation.py
  https://github.com/JackHopkins/factorio-learning-environment/blob/v0.3.0/fle/env/gym_env/registry.py
- Native verifier, setup, and all task definitions:
  https://github.com/JackHopkins/factorio-learning-environment/blob/v0.3.0/fle/eval/tasks/throughput_task.py
  https://github.com/JackHopkins/factorio-learning-environment/blob/v0.3.0/fle/eval/tasks/task_abc.py
  https://github.com/JackHopkins/factorio-learning-environment/blob/v0.3.0/fle/eval/tasks/task_definitions/lab_play/throughput_tasks.py
- Image, configuration, scenario, and server ports:
  https://github.com/JackHopkins/factorio-learning-environment/blob/v0.3.0/fle/cluster/run_envs.py
- Actual prototype and recipe enum names / supported namespace:
  https://github.com/JackHopkins/factorio-learning-environment/blob/v0.3.0/fle/env/game_types.py
  https://github.com/JackHopkins/factorio-learning-environment/blob/v0.3.0/fle/env/namespace.py
- Release dependency metadata:
  https://github.com/JackHopkins/factorio-learning-environment/blob/v0.3.0/pyproject.toml
- TypeSafe HTTP request/response schema, Choice limits, errors:
  https://docs.typesafe.ai/api
- Jev model version and token limits:
  https://docs.typesafe.ai/models
- Jev's non-generative typed-question design:
  https://docs.typesafe.ai/introduction
- Existing controller's repository instructions were inspected for context, not
  modified or incorporated wholesale:
  https://github.com/CompleteDotTech/jev-factorio-agent/blob/main/AGENTS.md

The package does not bundle or modify upstream FLE source or the Factorio game
binary. The power macro adapts the public release example, attributed here and
in NOTICE. The task names, API paths and version pins are interoperability data.
