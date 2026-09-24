# Setup validation

**91 offline tests passed; zero failures and errors.**

Python syntax compilation and construction of the adapter's Python wheel also passed.
The tests ran on Python 3.13.5; bootstrap targets Python 3.11.

## Native integration validation (2026-09-24)

Python 3.11 bootstrap installed pinned FLE commit
`714482a6fc3ed3da6b6288c35fb697c458415e31`; the 24-task import check
passed after pinning `a2a-sdk==0.3.26`. Docker started a dedicated Factorio
1.1.110 server, verified its image digest and loopback port bindings, and the
installed 1.1.110 GUI client joined at `127.0.0.1:35197`.

The native one-step engine smoke trial completed (task success false). A first
Jev gameplay smoke trial stopped before an action when the provider returned an
invalid probability distribution. The adapter now makes a bounded fresh attempt
while still rejecting malformed answers. The subsequent live Jev smoke trial
completed all four actions with 11 HTTP attempts and two native action errors;
the task verifier reported success false. This is one completed smoke trial,
not a 24-task evaluation or a score. The local `results/` receipts are ignored
by Git and include no API key.

The full 192-trial sweep has not been run. Its duration, provider cost, and
completion rate remain unknown.

## Live TypeSafe API smoke test (2026-09-24)

`api-smoke` passed with one request to the pinned `jev-1.13.0` model. It returned
the valid Choice answer `collect` for the coal inventory question, with 341 input
and 31 output tokens. The result is local under ignored `results/`; no key or
response body was added to this repository. This checks the hosted API path only.

See `offline-tests.xml`, `offline-tests.txt`, `package-build.log`,
`local-preflight.json`, `validation.json`, and `native-validation.json` for
machine-readable evidence. `validation.json` records the earlier preparation
session; `native-validation.json` records the later live validation.

The existing gameplay repositories were not modified.
