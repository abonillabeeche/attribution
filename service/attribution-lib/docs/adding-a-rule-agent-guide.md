# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

# Agent Guide: Add a New Attribution Rule

Use this procedure to add an Attribution Library rule with a minimal, evidence-backed diff.
This procedure permits local repository edits and local verification only.
Do not push a branch, create a pull request, or perform another remote write unless the user explicitly requests it.

Run commands from `service/attribution-lib` unless a step states otherwise.
Read [`adding-a-rule.md`](adding-a-rule.md) before using this procedure for the first time.

## Completion Criteria

Complete the task only when all of the following statements are true.

- The new rule has a unique, stable name and uses the correct observation source.
- A focused test failed before implementation and passes after implementation.
- Declarative branch coverage, when applicable, and runtime behavior are both tested.
- Every emitted symptom resolves through the symptom registry with approved metadata.
- The complete Attribution Library test gate passes, and the diff contains no unrelated changes.

## Step 1: Establish Scope

Inspect the checkout before editing.

```bash
git status --short --branch
rg -n -F 'distinctive input text' src/attribution_lib/bundled_rules
rg -n -F 'proposed symptom text' src/attribution_lib/bundled_rules/symptom_defaults.py
```

Preserve all pre-existing user changes.
Do not rename or rewrite an existing rule unless the request requires that behavior.

Record these acceptance criteria in the working notes.

1. Record the observation source and input format.
2. Record at least one exact matching input and one relevant near-miss.
3. Record the emitted event type, symptom, expected node or resources, and credited rule name.
4. Record whether the symptom is existing or new.
5. Record the approved outcome metadata when the symptom is new and outcome-bearing.

Stop and ask one concise question if a missing item requires a semantic decision.
In particular, do not infer whether evidence is `bad_node` or `interesting_node`, and do not invent outcome or cascade metadata.

## Step 2: Select the Implementation Path

Use the smallest path that implements the required behavior.

1. Use a declarative leaf for one fixed `bad_node`, `interesting_node`, or `generic_event` emission.
2. Use `pick_one`, `try_all`, `catalog_lookup`, or `family` only when the requested control flow directly requires that form.
3. Use a Python processor when the rule requires secondary parsing, state, context lookup, or a typed payload.
4. Use an existing Python rule pattern for a filter, refiner, collector, or extractor accumulator.

For a declarative rule, edit the nearest source-specific TOML file under `src/attribution_lib/bundled_rules/`.
Do not create a new file when an existing file already owns that source and rule shape.

For a Python processor, register a module-level function with `@rule_processor("namespace:name")` in a loaded top-level `*.py` file.
Reference it from a TOML `[[extractor]]` through `processor = "namespace:name"` and declare every possible `derived_rules` and `derived_event_types` value.
Follow the nearest processor and its tests rather than introducing a new abstraction.

## Step 3: Add a Failing Runtime Test

Prefer a case in an existing top-level `*.test.toml` file when an existing runner can express the behavior.
The available runner schemas are defined in `tests/rule_data_runner.py` and executed by `tests/test_rule_data.py`.

For example, add an application-log case with the following shape.

```toml
[[cases]]
description = "checkpoint permission failure identifies the application rule"
line = "checkpoint save failed: Permission denied"
expect = "bad"
expected_symptom = "checkpoint permission denied"
expected_rule = "ApplogCheckpointPermissionDenied"
```

Use a co-located `*_test.py` module under `src/attribution_lib/bundled_rules/tests/` when TOML cannot express the assertion.
Use shared fixtures from `test_support/` instead of importing test helpers from `tests/`.

Run only the new behavior test and confirm that it fails for the expected missing-rule behavior.

```bash
uv run --frozen pytest -n 4 tests/test_rule_data.py -q -k checkpoint
```

Do not continue if the test passes before the implementation.
Find whether an existing rule already handles the case or whether the test failed to select the intended case.

## Step 4: Implement the Minimal Rule

For a declarative leaf, add the extractor and its inline coverage cases together.

```toml
[[extractor]]
name     = "ApplogCheckpointPermissionDenied"
match_re = 'checkpoint save failed: Permission denied'
emit     = { type = "bad_node", symptom = "checkpoint permission denied" }

[[extractor.cases]]
line    = "checkpoint save failed: Permission denied"
expect  = "bad"
symptom = "checkpoint permission denied"

[[extractor.cases]]
line   = "checkpoint save completed"
expect = "none"
```

Apply these constraints while editing.

- Inherit file-level `author` and `sources` values when editing an existing TOML file.
- Set `author = "NVIDIA Attribution team"` and enum member names such as `sources = ["APPLOG"]` when creating a file.
- Use named regular-expression captures and reference them with `{name}` only where the emitted template needs them.
- Omit `derived_rule` when provenance should use the extractor name.
- Do not use `untested` to bypass ordinary inline branch coverage.

For `when`, include inline cases that make the expression both true and false.
For `pick_one`, reach every branch and the default.
For `try_all`, exercise both sides of every guarded event.

## Step 5: Register the Symptom

Skip this step only when existing registry metadata gives the emitted symptom the intended vocabulary, outcome, and cascade behavior.
Verify exact declarations, fallback-prefix resolution, and outcome-prefix behavior in `src/attribution_lib/bundled_rules/symptom_defaults.py` before deciding to skip it.

Add the smallest approved declaration when the symptom is new.

- Use `outcome_symptom(...)` for a symptom that can select a final outcome.
- Use `known_symptom(...)` for vocabulary-only evidence.
- Use `cascade_symptom(...)` only for symptom-pruning metadata.

Do not edit the legacy `RegisteredSymptoms` enum.
Do not copy outcome metadata from a textually similar symptom unless checked-in behavior or an accepted design decision establishes the same semantics.
Stop and request the missing decision when `outcome`, `OutcomePriority`, `doc`, `hw_cause`, or cascade behavior is not established.

## Step 6: Reach Green on the Focused Test

Load the production catalog to catch TOML syntax, duplicate names, invalid sources, invalid regular expressions, unresolved expressions, incomplete inline coverage, and symptom declaration errors.

```bash
uv run --frozen python -c 'from attribution_lib.core import setup_rules; setup_rules()'
```

Run the focused runtime test again.

```bash
uv run --frozen pytest -n 4 tests/test_rule_data.py -q -k checkpoint
```

If the test uses a co-located Python module, run that exact module instead.
Fix the implementation, not the expected result, unless source evidence proves that the expectation was wrong.

## Step 7: Verify the Catalog and Full Suite

Capture the loaded rule inventory.

```bash
uv run --frozen python scripts/rule_inventory.py dump -o /tmp/attribution-rules.json
rg -n 'ApplogCheckpointPermissionDenied' /tmp/attribution-rules.json
```

Inspect the inventory entry and verify the rule name, source, matcher, author, tags, form, and emit or processor definition.

Run the complete Attribution Library gate from the repository root.

```bash
(cd ../.. && bash .ci/run-tests.sh attribution-lib)
```

Run Ruff only when the change includes Python.

```bash
uv run ruff format --check --config ruff.toml
uv run ruff check --config ruff.toml
```

Inspect the final local diff.

```bash
git diff --check
git status --short
git diff -- .
```

Report the created or modified rule files, test files, symptom declarations, and exact verification results.
Leave the changes uncommitted unless the user requested a commit.
Never push without explicit user authorization.

## Stop Conditions

Stop and ask for direction when any of these conditions applies.

- The requested evidence can reasonably map to more than one symptom or outcome.
- A new match overlaps an existing rule, and the expected coexistence or precedence is unclear.
- The implementation requires a new rule type, event type, expression helper, test runner, or engine behavior.
- The full test gate reveals a failure outside the changed rule and its direct metadata.
- Three attempted fixes fail, which makes the assumed input, source, or expected outcome doubtful.
