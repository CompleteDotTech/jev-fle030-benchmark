# Setup validation

**91 offline tests passed; zero failures and errors.**

Python syntax compilation and construction of the adapter's Python wheel also passed.
The tests ran on Python 3.13.5; bootstrap targets Python 3.11.

## Not executed

The FLE dependency installation, native Gym/FLE imports, Docker image startup,
and real Factorio benchmark episodes were not executed in the preparation
environment. Docker and FLE were absent. No score is claimed. The synthetic
end-to-end test substitutes both HTTP and the engine.

## Live TypeSafe API smoke test (2026-09-24)

`api-smoke` passed with one request to the pinned `jev-1.13.0` model. It returned
the valid Choice answer `collect` for the coal inventory question, with 341 input
and 31 output tokens. The result is local under ignored `results/`; no key or
response body was added to this repository. This checks the hosted API path only.

See `offline-tests.xml`, `offline-tests.txt`, `package-build.log`,
`local-preflight.json` and `validation.json` for machine-readable evidence.

The existing gameplay repositories were not modified.
