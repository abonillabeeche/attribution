How Attribution Works
=====================

There are many parts involved in a system that does automated job attribution: scheduler interfaces, telemetry and log ingestion, rule processing, reporting, and aggregation. 

This document aims to describe how the rule processing component of attribution works; this is the core logic that analyses the evidence available to the system and produces the report.

## Elements of Attribution

This covers the core concepts of attribution.

### Symptoms

The fundamental element in attribution is the symptom. This is a piece of concrete evidence that the attribution system recognizes. One can associate them with human-readable items like "ECC Error" or "IB Error-12", but they also carry other semantic information that is used in attribution. 

### Outcomes

An outcome is a category that helps identify the type of failure that occurred. 

N.B. Outcomes will become compound in the feature future, allowing a set of semantically orthogonal values to be combined.

### Sources

Primary data for attribution comes from logs, metrics, and telemetry. It is important to track this information throughout the attribution process, so information about the provenance of a given internal representation (symptom, outcome, event, etc) is carried with it. A source will often say from which rule the item originated, as well as the line number, time, and type of data that produced it.

## Attribution Process Overview

### State management

Attribution stores the bulk of its state in a relational database. The is non-normatively done in an in-memory database, with tables for rules & events. (Event tables are per-job)

<!-- TODO(figure) add diagram showing basic database layout -->

### Events

The main objects manipulated during attributions are semi-structured records called "events"; these include source information, type information, resource association, and an unstructured "payload" that is specific to each type. 

<!-- TODO(figure) add diagram showing event layout -->

#### Bad nodes

Many events indicate an issue that is local to a node; a so-called "bad node event". These carry a symptom and associated node and are passed further down the pipeline to be verified and manipulated. 

#### Interesting nodes

Still other events are used to indicate that an anomaly, but not necessarily a fatal one, occurred. These "interesting node" events are used for development of further rules or debugging.

### Rules 

Attribution is essentially the structured application of a series of rules. Rules have unique names and some metadata that indicate their type and provenance. The rule loader deserializes and initializes rule objects from storage, then passes them to the rule engine for execution.

<!-- TODO(figure) show required elements for rule representation -->

### Rule Engine

As mentioned above, the rule engine accepts initialized rules from the rule loader and organizes them for execution. Attribution runs in distinct phases, as described below, and the rule engine marshals the proper rules to be executed at the correct time. It also prepares environments and contexts for rules to be applied properly, and arranges the interface with the rule & event database. 

### Rule Loader

The rule loader is responsible for  preparing rules for execution. For 'plugin'-type rules that appear as code, it is in charge of performing imports in proper sequence. For declarative rules, it is responsible for parsing and building the rule objects from source files. This includes verifying that rule dependencies exist and are compliant. There is also a global consistency check to enforce that rules have unique names. 

## Ingest-Attribution Cycle

While we typically think of attribution as a monolithic entity, it is sometimes useful to perform it incrementally; this reflects a natural pattern in production environments where some signals from a job may become available more quickly than others. It can be desirable to obtain a preliminary attribution based on whatever information is available initially, and to refine that as slower signals arrive.

<!-- TODO(figure) ingestion-attribution cycle diagram -->

For this reason, the entire attribution process has two independent, repeatable components: ingestion, where observations are fed to the system and processed, and attribution, where attribution is preformed using whatever observations have been ingested thus for. These two operations may be performed repeatedly, in any combination of orders.

Naturally, attribution prior to any ingestion will have no useful information, and it is similarly redundant to request repeated attributions without ingestion between them. Finally, ingestion without subsequent attribution leaves that data unused. 

## Detailed Attribution Phases

There are distinct, ordered phases to the attribution process. Each of these deals with a different type of data and uses a different type of rule to effect action in the system. 

<!-- TODO(figure) add diagram showing phases -->

### Phase 1: Extraction

Most observations are at least partially unstructured; raw application logs may just be plain text, lacking timestamps or clear node/rank associations. Some data may have a clear timestamp and node, but a plaintext body. A critical part of attribution is to take unstructured data and identify relevant patterns; in effect, to produce structured records (i.e., events).

The first phase is extraction, where extractor and extractor-accumulator rules are run. These tend to rely on various forms of text matching to identify and extract data that may be useful for attribution in the form of events. 

Critically, the extractor phase treats the event table as write-only; this is to ensure there is no coupling or dependency between extractor rules. 

The extractor phase lines up closely with the 'ingestion' component in the ingestion-attribution cycle; while it is not normative that observations are eagerly extracted into events, this is the natural approach. 

### Phase 2: Filtering

Filter are run next, after extractor rules. Filter rules explicitly can read and write the event table, and their role is to handle inter-event interactions. The most common example of this is when a bad node event is 'demoted' to an interesting node because of some other event that occurred. Filter rules each have a priority, which are effectively used to produce discrete strata, and are applied in priority order. 

### Phase 3: Refinement

The refinement stage looks at all of the symptoms that have been collected in bad node events and considers them as a whole. Like the filtering phase, there are priorities that act as de-facto sub-phases that control the order that refiner rules are run. 

First, the `SCRUB` priority looks at each node individually and considers the symptoms that have manifested for that node. The rules applied here will demote or remove subordinate or noisy symptoms. 

After `SCRUB`, all remaining symptoms across all nodes are aggregated into a set and the `FINAL` rules are run demote/remove rules based on known cascading relationships. When this sub-phase finishes, per-node symptoms (from bad node events or others) are cleaned up to reflect discarded/demoted symptoms. 

After `FINAL`, the remaining symptoms are mapped to an outcome, which is used in the final report. 

There is a further sub-phase of `POST_OUTCOME` rules that take the computed outcome as well as the remaining symptoms to inform the final result.

### Phase 4: Collections

Collector rules do not strictly affect the attribution result; instead, they exist to help surface useful information that may have been collected into the event table during the attribution process. This may be relevant job parameters or component versions found during the attribution process. 

### Phase 5: Reporting

There not rule specific to the reporting stage; instead, remaining bad nodes are collected, and the outcome, plus the root cause symptom and any collector results are formatted and returned in the attribution result. 

## Rule Types

### Extraction

As mentioned above, extractor rules are used to prepare unstructured or semi-structured input data into the structured event table used by later phases. There are a great number of extractor rules, reflecting the breadth of the space of unstructured observations. 

Extractors are fundamentally string-oriented; they generally have a regular expression that characterizes the basic form they match on, and some logic shape the event or events they produce.  For each observation line ingested, rules engine determines which extractor rule(s) apply to it and executes them, adding the resulting events to the event table. Basic job information can be read by extractor rules, but recall that the event table is write-only during this phase.

Extractor rules are almost exclusively expressed in declarative form (TOML), with some support functions in Python plugins. 

Basic extractor rules come in three varieties:

#### Individual

These are simply discrete extractor rules, expressing some unique pattern of interest. They stand in contrast to catalog and family-based extractor rules. 

<!-- TODO(figure) example of an individual declarative extractor rule -->

#### Family 

Extractor family rules are essentially a shorthand convenience for a group of extractor rules that share some common structure. They are expanded from a template upon load time and manifested as distinct rules. 

#### Catalog 

Extractor catalog rules exist as a way to conveniently include a catalog lookup as an compound extractor rule. There are no expanded at load time and stand as a one-to-many lookup rule.

#### Extractor-Accumulator

Extractor-accumulator rules are a special case that stand distinct from the usual extractor rule. They are run during the extractor phase, but they are state machines that can consider multiple lines at once. Extractor-accumulator rules have an initial trigger pattern, and then are fed subsequent lines from the same observation until the opt out. When finalized, they may produce some events. 

Extractor-accumulator rules are very niche and complex, and are only supported as Python plugins. 

Extractor rules are so numerous, and are applied to so many incoming lines of observations, that we use a special acceleration structure to speed up the matching process. It is possible for a set of rules to confound some of the heuristics of this acceleration structure, generally by having overlapping or overly-broad regular expressions for matching. Care should be taken that the rule corpus not drift into an inefficient or inter-dependent state. 

### Filter

As mentioned above, filter rules handle inter-event interactions. Filter rules most commonly demote events based on other events that have occurred. Some events produced during extraction actively indicate what types of demotion they may be eligible for, while others are demoted by markers that a given filter rule might identify---for example, a certain type of symptom. 

To control the order filter rules are executed in, their definitions are accompanied by a priority, generally managed in discrete strata: `EARLY`, `MID`, `STANDARD`, `LATE`. 

Filters are exclusively written as Python plugins. 

<!-- TODO(figure) example filter rule -->

### Refiner

Refiner rules are focused on manipulating sets of symptoms to capture known cascading and other interactions. The intention is to reduce the number of symptoms present during the final stages of attribution for a clearer signal. 

Like filter rules, refiner rules have a priority, also managed in discrete strata: `SCRUB`, `FINAL`, `POST_OUTCOME`. Unlike filter rules, the refiner priorities have distinct boundaries with different semantics.

Rules that are `SCRUB` or later (but before `FINAL`) operate on node-centric sets of symptoms. Rules that occur in `FINAL` or after, up to `POST_OUTCOME` operate on job-wide symptoms. Before `POST_OUTCOME` begins, these changes to the global symptom set are back-propagated to the node symptom representations (generally, bad-node events.) The last sub-phase, from `POST_OUTCOME` onward, operates on the global symptom set and chosen outcome. 

Refiner rules are exclusively written as Python plugins. 

<!-- TODO(figure) example filter rule -->

### Collector

Collector rules read the event table and return dictionaries, generally with keys that identify semantically useful fields and bodies composed of the digested events. They are the simplest form of rule, and are run at the end of attribution. They are solely declared as Python plugins. 

<!-- TODO(content) cover outcome mapping -->
<!-- TODO(content) cover checkpointing  -->

# Appendices

## Initialization order

1. Idempotency check: if already initialized and force=True isn't passed, setup_rules() returns immediately.
2. Resolve rule paths: defaults to the package's bundled bundled_rules/ directory unless explicit paths are given. 
3. Set global config: marks attribution_lib.initialized = True, stores the node-domain resolver, and optionally configures node-name-mapping / ignored-hostname-prefix settings. 
4. RuleLoader.load_all() does the actual loading pass:
   - Registers the four built-in rule types (collector, extractor, filter, refiner) via their @rule_type decorators.
   - Globs the rules directory for top-level *.py and *.toml files only (non-recursive, so bundled_rules/common/*.py is never loaded directly: only imported by the top-level rule modules), sorted, skipping *.test.toml.
   - Each .py file is exec'd fresh (module globals bound to the loader so its decorators register rules/symptoms); each .toml file goes through the declarative loader instead. Duplicate/conflicting registrations raise immediately.
   - loader.build() freezes everything into an immutable RuleEngine.
5. Store the engine as attribution_lib._rules_engine.
6. Compile the symptom registry: builds the runtime GeneratedSymptomRegistry (registered symptoms, outcome rules, metadata, aliases, docs) once from the loaded declarations, stored as attribution_lib._symptom_registry. 
