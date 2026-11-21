# RWX Blast Radius entry

This is a self-contained repository root for the 2026 Builders Buildathon RWX
track. Copy this folder's contents to a public team-owned repository. The image
uses the official pinned Python image, fetches sqlglot only at commit
`eb11aec4be8cb2122afe713a4816662c3f0fb2fa`, and verifies every fetched Python
file against the pristine coverage map's SHA256. Runtime is offline and requires
no packages beyond Python's standard library. Source is fetched during build,
so the repository stays below the 20 MB cap.

The selector applies each patch in memory. Existing function-body edits select
tests that executed the pristine function, read the source file, or belong to an
edited test module. Structural/module/import/fixture changes, new definitions,
unrecognized patches, unknown incoming tests, and source mismatches fall back
to every test. All selected tests are scheduled by exact integer milliseconds
over one through eight workers. No patches or sample answers are included here.

`coverage.json` is a plain, ordinary JSON Git file generated on the pristine pinned
source with the official Python3.13 image and requirements.lock. It maps test
IDs to executed functions and opened files. Function bitsets and path IDs reduce
the map from13.63MB to0.85MB;8,265,479 membership checks and identical sample
output establish equivalence for every outer-function query this selector accepts.
It contains no patch-answer or
edit-kind-answer lookup. Numbered incoming tests are remapped by their IDs.
The recorder runs process-pool tasks synchronously with task/result/exception
pickling to trace transport dependencies; process isolation and every child
subprocess are not reproduced. Therefore sample recall is evidence, not a
guarantee of hidden-test recall.

Build from this folder:

```sh
docker build --platform linux/amd64 -t buildathon-rwx:entry .
```

The production default is coverage selection. `--strategy balanced` selects
every test with optimized scheduling, and `--strategy starter` reproduces the
original three-worker baseline. All logs go to stderr.

## Attribution and license

MIT License. Built with AI assistance. Based on the organizer's Blast Radius
starter scheduler and exact scoring specification; sqlglot is upstream MIT
software by Toby Mao and contributors. The source map was generated during the
event from the pinned open-source repository. The organizer kit, Python base
image, and sqlglot are preexisting dependencies. No challenge solution existed
in the original workspace before this event session.

Official rules: https://www.joinbuilders.org/buildathon/tracks/blast-radius
Pinned source: https://github.com/tobymao/sqlglot/tree/eb11aec4be8cb2122afe713a4816662c3f0fb2fa
