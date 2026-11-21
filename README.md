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
edited test module. Existing data-file edits select observed pristine readers;
collection-loaded or unmapped data stays conservative. Same-structure module or
class value edits use a second pristine trace of receiver MROs, metadata-table
origins and imported globals. Before pruning these edits, a bounded offline
subprocess imports the patched modules; import failure or timeout selects all
tests. Python AST equivalence preserves encoding and type comments and still
includes observed raw-source readers; comments are never classified by label.
Structural/import changes, new definitions, dunder/external-state assignments,
unrecognized patches, unknown incoming tests, and source mismatches fall back
to every test. All selected tests are scheduled by exact integer milliseconds
over one through eight workers. No patches or sample answers are included here.

`coverage.json` is a plain, ordinary JSON Git file generated on the pristine pinned
source with the official Python 3.13 image and requirements.lock. It maps test
IDs to executed functions and opened files. Function bitsets and path IDs reduce
the original line map from 13.63 MB to 0.85 MB; 8,265,479 membership checks and identical sample
output establish equivalence for every outer-function query this selector accepts.
The extra pristine module and immutable-field bitsets bring the complete map to 0.98 MB.
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

The 30 public sample changes score 198.039 simulated seconds with zero misses;
three restricted Linux runs and the exact image command validate. This is local
evidence, not a prediction of final rank. Independent fixture and serializer
mutations retained every failing test. An independent DuckDB class-constant
mutation was checked in the full original test order: all eight failing methods
were selected. A source-comment mutation also passed all omitted tests.

## Regenerating pristine maps

Use the exact source commit, Python image digest and requirements.lock. Run
build_coverage.py on the pristine full source to generate raw line/open coverage.
Run compact_map.py against that same source to encode function intervals. Run
trace_consumers.py on pristine source for class/import consumers, then use
merge_consumers.py to merge that trace into the compact map. These scripts read
no challenge patches or sample answers. The committed map can be regenerated
and checked by SHA256 and membership equivalence. Process-pool instrumentation
and consumer approximations remain documented limitations.

## Attribution and license

MIT License. Built with AI assistance. Based on the organizer's Blast Radius
starter scheduler and exact scoring specification; sqlglot is upstream MIT
software by Toby Mao and contributors. The source map was generated during the
event from the pinned open-source repository. The organizer kit, Python base
image, and sqlglot are preexisting dependencies. No challenge solution existed
in the original workspace before this event session.

Official rules: https://www.joinbuilders.org/buildathon/tracks/blast-radius
Pinned source: https://github.com/tobymao/sqlglot/tree/eb11aec4be8cb2122afe713a4816662c3f0fb2fa

## Collection-event attribution

Function declaration lines, multiline signatures and default-annotation evaluation
are separate from function body execution. The collection map retains actual body
witnesses for normal functions and keeps generator, async, one-line and doc-only
ambiguities conservative. All 5,033 normal-function intervals were checked against
the original pristine trace; real trace unit tests cover declaration-only and
actual-body-call cases. A fresh independent BigQuery body mutation was evaluated
in the full original test order: its failing method was selected, with no omitted
failures among 1,619 passing methods. No new pristine execution or sample-answer
lookup was needed for this correction.

Regenerate after the existing compact-map steps with:

```sh
python repair_collection_map.py --raw-map raw-coverage.json --compact-map compact-consumers.json --source pinned-sqlglot --output coverage.json
```

## Immutable Dialect field attribution

An additional pristine trace records attribute reads on Dialect instances and
their metaclass, with receiver MRO ancestry, collection events, and shared
setup/teardown. Raw `__dict__` readers count as consumers of every eligible field.
Narrowing applies only when the entire AST is unchanged except same-type
immutable literal RHS values of existing class fields. Static source analysis
requires every declared owner to descend from Dialect and excludes fields with
bare-name reads, runtime field-name strings, outside writes, or module/metaclass
derivations. Fields read during collection retain the module fallback. Every
other metadata edit retains the previous module selection. Function consumers,
raw-source readers, source hashes, unknown-input fallbacks, and bounded patched
module import validation are retained.

The new pristine trace passed 1,620 methods, skipped one, and passed 25,440
subtests in 188.439s. Its source hashes match the function/module maps. An
additional import audit verified all 206 declared owners of the 59 static field
candidates are actual Dialect subclasses. The final map contains 190 eligible
class-qualified fields in 29 files; unobserved fields retain module masks.

A fresh independent PostgreSQL TYPED_DIVISION mutation was evaluated in the
full original test order. All seven failing methods were among 13 selected
tests; the preceding module selector selected 320 tests. Their scheduled costs
are 3.009s and 12.896s respectively. An earlier independent DuckDB INDEX_OFFSET
mutation's eight observed failures also remain selected: 35 tests, scheduled
4.388s, versus the preceding module selector's 452 tests and 27.454s. These are
local independent-mutation results; the 30 public sample selections remain
unchanged at 198.039s with zero misses. They do not establish final-test recall.

To regenerate from the same pristine source and locked research environment:

```sh
python inventory_fields.py --source pinned-sqlglot --output field-inventory.json
python audit_owners.py --source pinned-sqlglot --inventory field-inventory.json --output owner-audit.json
python trace_attributes.py --source pinned-sqlglot --output attribute-consumers.json --max-seconds 550
python merge_attributes.py --map collection-map.json --trace attribute-consumers.json --inventory field-inventory.json --output coverage.json
```

Tracing is an approximation of fixed test executions, including synchronous
pickle-roundtrip process-pool instrumentation. Arbitrary child-process reads and
state propagation beyond observed dependencies remain limitations. This version
keeps its previous fallbacks rather than pruning unknown data or structures.
