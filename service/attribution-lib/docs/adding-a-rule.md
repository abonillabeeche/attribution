# Add a New Attribution Rule

Use this guide to add an extractor rule to the NVIDIA Attribution Library.
An extractor rule recognizes evidence in one observation and emits a structured event that later stages use to produce a diagnosis.

This guide assumes that you are comfortable editing Python and TOML, but that you have not worked in this codebase.
Run all commands from `service/attribution-lib` unless a command states otherwise.

## Understand the Rule Flow

The Attribution Library processes a new extractor rule through the following flow.

1. `setup_rules()` loads every top-level `*.py` and `*.toml` file under `src/attribution_lib/bundled_rules/`.
2. The rule matches observations from one or more declared sources, such as `APPLOG`, `SYSLOG`, or `NODE_METRICS`.
3. The rule emits a bad-node event, an interesting-node event, or a generic event.
4. A bad-node or interesting-node event carries a symptom string and credited rule name.
5. The symptom registry resolves that string and supplies outcome and cascade metadata.

Files ending in `*.test.toml` are test data and are not loaded as production rules.
You do not need to add a declarative rule to a separate registration list.

## Gather the Required Evidence

Define these inputs before you edit a rule file.

- Record the observation source and at least one exact input that must match.
- Record a similar input that must not match when false positives are possible.
- Decide whether the evidence identifies a bad node, provides interesting context, or emits a non-attribution event.
- Reuse an existing symptom when it has the same meaning, or obtain an approved outcome, priority, and documentation anchor for a new symptom.
- Decide which rule name must appear in provenance as `source.rule`.

Search the existing catalog before adding a new rule or symptom.

```bash
rg -n -F 'distinctive text from the observation' src/attribution_lib/bundled_rules
rg -n -F 'proposed symptom text' src/attribution_lib/bundled_rules/symptom_defaults.py
```

Extend an existing rule when the evidence has the same meaning and output.
Create a new rule when the evidence needs a distinct matcher, symptom, provenance name, or test boundary.

## Choose the Smallest Rule Form

Prefer declarative TOML for fixed matching and emission behavior.
Use the following mapping to choose a form.

| Required Behavior | Rule Form | Example |
| --- | --- | --- |
| Emit one event after one regular-expression match. | Use a declarative leaf with `bad_node`, `interesting_node`, or `generic_event`. | [`applog_leaf_rules.toml`](../src/attribution_lib/bundled_rules/applog_leaf_rules.toml). |
| Choose the first matching result from ordered conditions. | Use `pick_one`. | [`applog_combinator_rules.toml`](../src/attribution_lib/bundled_rules/applog_combinator_rules.toml). |
| Emit several independently guarded events from one match. | Use `try_all`. | [`syslog_combinator_rules.toml`](../src/attribution_lib/bundled_rules/syslog_combinator_rules.toml). |
| Map a captured key through a table. | Use `catalog_lookup`. | [`syslog_sxid_rule.toml`](../src/attribution_lib/bundled_rules/syslog_sxid_rule.toml). |
| Generate similar literal-match rules from rows. | Use a `family`. | [`generic_keyword_family.toml`](../src/attribution_lib/bundled_rules/generic_keyword_family.toml). |
| Perform secondary parsing, stateful work, context lookup, or typed payload construction. | Use a registered Python processor referenced by a TOML extractor. | [`applog_processor_rules.toml`](../src/attribution_lib/bundled_rules/applog_processor_rules.toml). |

Filters, refiners, collectors, and extractor accumulators remain Python rule types.
Follow the nearest existing implementation and its co-located tests when your change belongs to one of those stages.

## Add a Declarative Leaf

Add a new stanza to the existing source-specific leaf file when one exists.
The following example detects an application-log error and emits one bad-node symptom.

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

The enclosing TOML file normally provides file-level `author` and `sources` values.
If you create a new file, set `author = "NVIDIA Attribution team"` and declare the required `sources` by enum member name.
The available member names are defined by `Source` in `src/attribution_lib/observation/inbound.py`.

Keep `name` unique and stable because inventories, tests, and provenance expose it.
If `emit.derived_rule` is absent, the emitted event receives the extractor `name` as its credited rule.
Set `derived_rule` only when the required `source.rule` value intentionally differs from the extractor name.

Use named regular-expression captures when the symptom or a condition needs a matched value.
Reference a capture in a symptom template with braces, as in `symptom = "error code {code}"`.
Use a bare expression in `when`, as in `when = "int(code) > 0"`.
The loader rejects unknown names, invalid regular expressions, unsafe optional-capture access, and unsupported keys.

## Cover Every Declarative Branch

Each declarative `emit` rule must contain inline `[[extractor.cases]]` entries or an explicit `untested` waiver.
Do not use `untested` for ordinary rule additions.

Inline cases are load-time coverage data.
They exercise every leaf guard, `pick_one` branch and default, and independently guarded `try_all` event.
A leaf with `when` needs cases for both the true and false sides.
A leaf without `when` needs at least one emitting case.

Inline cases do not replace runtime behavior tests.
They do not fully assert emitted event types, credited rule names, payloads, or the complete attribution pipeline.

## Add a Runtime Behavior Test

Use a top-level `*.test.toml` file under `src/attribution_lib/bundled_rules/` when the case fits an existing data runner.
The centralized discovery and runners live in `tests/rule_data_runner.py` and `tests/test_rule_data.py`.

The following example uses the `applog_single_line` runner.

```toml
[meta]
runner = "applog_single_line"

[[cases]]
description = "checkpoint permission failure identifies the application rule"
line = "checkpoint save failed: Permission denied"
expect = "bad"
expected_symptom = "checkpoint permission denied"
expected_rule = "ApplogCheckpointPermissionDenied"

[[cases]]
description = "successful checkpoint does not match the permission failure rule"
line = "checkpoint save completed"
expect = "no_match"
```

Add cases to an existing source-specific `*.test.toml` file instead of repeating its `[meta]` table.
Use a co-located Python test when the case requires mocks, multi-step event choreography, or detailed event-stream inspection.
Keep bundled-rule Python tests under `src/attribution_lib/bundled_rules/tests/` so production rule discovery does not load them.

## Register a New Symptom

Skip this step only when existing registry metadata already gives the emitted symptom its intended vocabulary, outcome, and cascade behavior.
Check exact declarations, approved fallback prefixes, and outcome prefixes before deciding to skip it.
Add a new declaration to `src/attribution_lib/bundled_rules/symptom_defaults.py` when the symptom is new.

Choose the declaration helper based on the symptom's role.

- Use `outcome_symptom(...)` when the symptom can select the final outcome.
- Use `known_symptom(...)` when the symptom belongs to the vocabulary but does not select an outcome.
- Use `cascade_symptom(...)` when the declaration only defines pruning behavior.

Do not add new symptoms to the legacy `RegisteredSymptoms` enum.
Do not guess an outcome, `OutcomePriority`, hardware cause, cascade edge, or documentation anchor.
These values change the final diagnosis and require evidence or an accepted domain decision.

An undeclared symptom is preserved as evidence with an `unknown-symptom-` prefix and does not produce the intended classification.
Outcome selection matches declaration prefixes with `startswith`, so verify that a new prefix does not unintentionally shadow another declaration.

## Verify the Rule

Run the focused behavior test first.
Replace `checkpoint` with a distinctive token from your new test description.

```bash
uv run --frozen pytest -n 4 tests/test_rule_data.py -q -k checkpoint
```

Load the complete bundled catalog through the production setup path.

```bash
uv run --frozen python -c 'from attribution_lib.core import setup_rules; setup_rules()'
```

Capture an inventory and confirm that the new rule is present with the expected matcher, source, author, tags, and emit definition.

```bash
uv run --frozen python scripts/rule_inventory.py dump -o /tmp/attribution-rules.json
rg -n 'ApplogCheckpointPermissionDenied' /tmp/attribution-rules.json
```

Run the complete Attribution Library test gate from the repository root.

```bash
(cd ../.. && bash .ci/run-tests.sh attribution-lib)
```

Review the final diff and confirm that every changed line belongs to the rule, its symptom metadata, its tests, or its documentation.

```bash
git diff --check
git diff -- .
```
