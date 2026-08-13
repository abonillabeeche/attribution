# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

import hashlib
import importlib.util
import sys
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from dataclasses import (
    dataclass,
    fields as dc_fields,
)
from datetime import datetime
from itertools import groupby
from pathlib import Path
from typing import Any, NamedTuple, Optional

from loguru import logger
from pydantic import ValidationError

from attribution_lib.decision_trace_recorder import DecisionRecorder, NodeSymptomSnapshot, snapshot_bad_nodes
from attribution_lib.declarative import load_toml_rules
from attribution_lib.declarative.context import (  # noqa: F401 (re-exported public API)
    _EXPR_HELPER_RESERVED,
    EXPR_HELPER_INJECTED_PARAMS,
    _NamespaceProvider,
    _ProviderDecorator,
    _using_module_globals,
    _using_rules_engine,
    const,
    expr_helper,
    rows,
    rule_processor,
)
from attribution_lib.events import EventStream
from attribution_lib.exceptions import (
    DuplicateRuleError,
    InvalidRuleParams,
    RuleAcceptsNoParamsError,
    RuleIngestionError,
    UnknownResourceError,
    UnknownRuleTypeError,
)
from attribution_lib.job_info import JobInfo
from attribution_lib.logline_filtering import log_ignored_node_line, log_ignored_time_line
from attribution_lib.observation.inbound import Source as ObservationSource
from attribution_lib.observation.processing import EntryProtocol, EntrySourceBase
from attribution_lib.prefilters import (  # noqa: F401 (re-exported public API)
    _METRIC_SPECS,
    _PRE_FILTERS,
    MetricSpec,
    PreFilterCallable,
    PreFilterSpec,
    get_metric_spec,
    get_pre_filter,
    register_metric_spec,
    register_pre_filter,
)
from attribution_lib.rule_types.definitions import (  # noqa: F401 (re-exported public API)
    CollectorContext,
    CollectorFormatter,
    CollectorProcessor,
    CollectorRule,
    EventTriple,
    ExecutionContext,
    ExtractionContext,
    ExtractorAccumulator,
    ExtractorAccumulatorRule,
    ExtractorProcessor,
    ExtractorRule,
    FilterContext,
    FilterPriority,
    FilterProcessor,
    FilterRule,
    RefinerContext,
    RefinerProcessor,
    RefinerRule,
    Rule,
    RuleContext,
    RuleId,
    RuleLocation,
    RuleParameters,
    RuleParamsBase,
    TwoStageSourceMatcher,
)
from attribution_lib.rule_types.observation import ObservationProcessor  # noqa: F401 (re-exported)
from attribution_lib.rule_types.registration import (  # noqa: F401 (re-exported public API)
    _get_caller_location,
    collector_def,
    declare_event_types,
    declare_rule_names,
    extractor_accumulator_def,
    filter_def,
    normalize_tags,
    refiner_def,
)
from attribution_lib.symptoms.declarations import (  # noqa: F401 (re-exported public API)
    CascadeScope,
    DagDiscardBehavior,
    OutcomePriority,
    SymptomCategory,
    SymptomDeclaration,
)
from attribution_lib.symptoms.predicate_registry import SymptomPredicate  # noqa: F401 (re-exported)
from attribution_lib.symptoms.registration import (  # noqa: F401 (re-exported public API)
    cascade_symptom,
    known_symptom,
    outcome_symptom,
    symptom_predicate,
)


class RefinerEntry(NamedTuple):
    """A refiner rule with its execution metadata."""

    priority: int
    sequence: int
    name: str
    processor: "RefinerProcessor"


@dataclass
class _LoadSnapshot:
    """Snapshot of all RuleEngine fields that may be mutated during load.

    Field names match the corresponding RuleEngine attribute names exactly so
    capture() and restore() can iterate dc_fields() without a name mapping.
    The special fields ``_pre_filters`` and ``_metric_specs`` capture the module-level
    ``_PRE_FILTERS`` and ``_METRIC_SPECS`` dicts (not engine attributes) and are
    handled explicitly in capture/restore.
    """

    const_values: dict
    extractor_rules: dict
    filter_rules: dict
    extractor_accumulator_rules: dict
    refiner_rules: dict
    collector_rules: dict
    declared_rule_names: set
    declared_event_types: set
    declarative_emit: dict
    record_tables: dict
    expr_helpers: dict
    expr_helper_injections: dict
    rule_processors: dict
    symptom_declarations: list
    symptom_predicates: dict
    _filter_execution_order: list
    _refiner_execution_order: list
    _filters_sorted: bool
    _filters_by_phase: dict
    _refiners_sorted: bool
    _refiners_by_phase: dict
    matcher: object  # Optional[TwoStageSourceMatcher]; copied by reference (immutable identity)
    _pre_filters: dict  # snapshot of the module-level _PRE_FILTERS
    _metric_specs: dict  # snapshot of the module-level _METRIC_SPECS

    @classmethod
    def capture(cls, e: "RuleEngine") -> "_LoadSnapshot":
        copy: dict[str, Any] = {}
        for f in dc_fields(cls):
            if f.name == "_pre_filters":
                copy["_pre_filters"] = {
                    k: PreFilterSpec(
                        include_terms=list(v.include_terms),
                        exclude_terms=list(v.exclude_terms),
                        callables=list(v.callables),
                    )
                    for k, v in _PRE_FILTERS.items()
                }
            elif f.name == "_metric_specs":
                copy["_metric_specs"] = {k: MetricSpec(thresholds=dict(v.thresholds)) for k, v in _METRIC_SPECS.items()}
            else:
                v = getattr(e, f.name)
                copy[f.name] = type(v)(v) if isinstance(v, (dict, list, set)) else v
        return cls(**copy)

    def restore(self, e: "RuleEngine") -> None:
        for f in dc_fields(self):
            if f.name == "_pre_filters":
                _PRE_FILTERS.clear()
                _PRE_FILTERS.update(self._pre_filters)
            elif f.name == "_metric_specs":
                _METRIC_SPECS.clear()
                _METRIC_SPECS.update(self._metric_specs)
            else:
                setattr(e, f.name, getattr(self, f.name))


class RuleEngine:
    """Execute rules against sources"""

    def __init__(self) -> None:
        self.extractor_rules: dict[RuleId, ExtractorRule] = {}
        self.filter_rules: dict[RuleId, FilterRule] = {}
        self.extractor_accumulator_rules: dict[RuleId, ExtractorAccumulatorRule] = {}
        self.refiner_rules: dict[RuleId, RefinerRule] = {}
        self.collector_rules: dict[RuleId, CollectorRule] = {}
        self.declarative_emit: dict[str, str] = {}
        self.declared_rule_names: set[str] = set()
        self.declared_event_types: set[str] = set()
        self.expr_helpers: dict[str, "Callable[..., object]"] = {}
        self.const_values: dict[str, object] = {}
        self.record_tables: dict[str, dict] = {}
        self.rule_processors: dict[str, "Callable[..., object]"] = {}
        self.expr_helper_injections: dict[str, frozenset] = {}
        self.symptom_declarations: list[SymptomDeclaration] = []
        self.symptom_predicates: dict[str, SymptomPredicate] = {}
        self.matcher: Optional[TwoStageSourceMatcher] = None
        self._filter_execution_order: list[tuple[int, int, FilterProcessor]] = []
        self._filters_sorted: bool = True
        self._filters_by_phase: dict[int, list[FilterProcessor]] = {}
        self._refiner_execution_order: list[RefinerEntry] = []
        self._refiners_sorted: bool = True
        self._refiners_by_phase: dict[int, list[tuple[str, RefinerProcessor]]] = {}

    @property
    def rules(self) -> dict[RuleId, Rule]:
        """Combined view of all rules (for backward compatibility)."""
        all_rules: dict[RuleId, Rule] = {}
        all_rules.update(self.extractor_rules)
        all_rules.update(self.filter_rules)
        all_rules.update(self.extractor_accumulator_rules)
        all_rules.update(self.refiner_rules)
        all_rules.update(self.collector_rules)
        return all_rules

    @property
    def all_rule_names(self) -> set[str]:
        """All known rule names: registered rules + explicitly declared synthetic names."""
        return set(self.rules.keys()) | self.declared_rule_names

    @property
    def all_event_types(self) -> set[str]:
        """All declared event type names."""
        return set(self.declared_event_types)

    def register_rule(self, rule: Rule) -> None:
        """Register a rule, dispatching to correct storage based on type."""
        if isinstance(rule, ExtractorRule):
            self._register_extractor(rule)
        elif isinstance(rule, FilterRule):
            self._register_filter(rule)
        elif isinstance(rule, ExtractorAccumulatorRule):
            self._register_extractor_accumulator(rule)
        elif isinstance(rule, RefinerRule):
            self._register_refiner(rule)
        elif isinstance(rule, CollectorRule):
            self._register_collector(rule)
        else:
            raise UnknownRuleTypeError(f"Unknown rule type: {type(rule)}")

    def register_symptom_declaration(self, declaration: SymptomDeclaration) -> None:
        """Register declarative symptom metadata loaded from a rule module."""
        for existing in self.symptom_declarations:
            if existing.prefix != declaration.prefix or existing.scope is not declaration.scope:
                continue
            if existing == declaration:
                return
            existing_location = existing.location if existing.location is not None else RuleLocation("unknown", 0)
            new_location = declaration.location if declaration.location is not None else RuleLocation("unknown", 0)
            raise RuleIngestionError(
                f"Conflicting symptom declaration for {declaration.prefix!r}: "
                f"first at {existing_location.file}:{existing_location.line}, "
                f"conflict at {new_location.file}:{new_location.line}"
            )
        self.symptom_declarations.append(declaration)

    def register_symptom_predicate(self, name: str, predicate: SymptomPredicate) -> None:
        """Register a conditional-discard predicate under ``name`` for this engine.

        Cascade rules reference the predicate by name in ``conditional_discards``;
        the compiled registry resolves the name to this callable.
        """
        existing = self.symptom_predicates.get(name)
        if existing is not None and existing is not predicate:
            raise RuleIngestionError(f"Conflicting symptom predicate registered for {name!r}")
        self.symptom_predicates[name] = predicate

    def _check_duplicate(self, name: RuleId, location: RuleLocation) -> None:
        """Check for duplicate rule names across all rule types."""
        for store in (
            self.extractor_rules,
            self.filter_rules,
            self.extractor_accumulator_rules,
            self.refiner_rules,
            self.collector_rules,
        ):
            existing = store.get(name)
            if existing is not None:
                raise DuplicateRuleError(
                    f"Duplicate rule '{name}': "
                    f"first at {existing.location.file}:{existing.location.line}, "
                    f"duplicate at {location.file}:{location.line}"
                )

    def _register_extractor(self, rule: ExtractorRule) -> None:
        """Register an extractor rule."""
        self._check_duplicate(rule.name, rule.location)
        self.matcher = None  # Invalidate matcher
        self.extractor_rules[rule.name] = rule

    def _register_filter(self, rule: FilterRule) -> None:
        """Register a filter rule."""
        self._check_duplicate(rule.name, rule.location)
        self.filter_rules[rule.name] = rule
        self._filter_execution_order.append((rule.priority, len(self._filter_execution_order), rule.processor))
        self._filters_sorted = False

    def _register_extractor_accumulator(self, rule: ExtractorAccumulatorRule) -> None:
        """Register an extractor-accumulator rule."""
        self._check_duplicate(rule.name, rule.location)
        self.matcher = None  # Invalidate matcher
        self.extractor_accumulator_rules[rule.name] = rule

    def _register_refiner(self, rule: RefinerRule) -> None:
        """Register a refiner rule."""
        self._check_duplicate(rule.name, rule.location)
        self.refiner_rules[rule.name] = rule
        self._refiner_execution_order.append(
            RefinerEntry(rule.priority, len(self._refiner_execution_order), rule.name, rule.processor)
        )
        self._refiners_sorted = False

    def _register_collector(self, rule: CollectorRule) -> None:
        """Register a collector rule."""
        self._check_duplicate(rule.name, rule.location)
        self.collector_rules[rule.name] = rule

    def run_collectors(
        self,
        event_stream: EventStream,
        job_info: "JobInfo",
        rule_params: Optional[Mapping[RuleId, RuleParameters]] = None,
    ) -> dict[str, Any]:
        """Run all registered collectors and merge their digest outputs.

        Each collector's formatter returns a dict of digest key-value pairs.
        Duplicate keys across collectors are logged as errors (first value kept).
        """
        params_by_rule = rule_params or {}
        digest: dict[str, Any] = {}
        for rule_id, rule in self.collector_rules.items():
            try:
                params = self.parse_collector_params(rule, params_by_rule.get(rule_id))
                result = rule.process(event_stream, job_info, params)
            except Exception:
                logger.opt(exception=True).error(f"Collector '{rule_id}' failed")
                continue
            for key, value in result.items():
                if key in digest:
                    logger.error(
                        f"Duplicate digest key '{key}': collector '{rule_id}' "
                        f"would overwrite existing value (keeping first)"
                    )
                else:
                    digest[key] = value
        return digest

    @staticmethod
    def parse_collector_params(rule: CollectorRule, raw: Optional[RuleParameters]) -> Optional[RuleParamsBase]:
        """Parse a ``RuleParameters`` envelope against the rule's params_model.

        Returns:
            ``None`` if the rule declares no ``params_model``; otherwise
            constructs the model (with defaults when ``raw`` is ``None``).
        Raises:
            ``RuleAcceptsNoParamsError``: If params are supplied for a rule with
                no ``params_model``.
            ``InvalidRuleParams``: If the payload fails ``params_model`` validation.
        """
        if rule.params_model is None:
            if raw is not None and raw.params != {}:
                raise RuleAcceptsNoParamsError(rule.name)
            return None

        params_data = raw.params if raw is not None else {}
        try:
            return rule.params_model(**params_data)
        except ValidationError as e:
            raise InvalidRuleParams(rule.name, e) from e

    def finalize(self) -> None:
        """Build the TwoStageMatcher and sort filter execution order."""
        if self.matcher is not None:
            logger.warning("Redundant rules engine finalization")

        # Collect all patterns by source type — matcher is rule-type-agnostic
        patterns_by_source: dict[ObservationSource, dict[RuleId, str]] = {}
        for rule in self.extractor_rules.values():
            if not rule.match_re:
                continue
            for source in rule.source_filters:
                patterns_by_source.setdefault(source, {})[rule.name] = rule.match_re
        for acc_rule in self.extractor_accumulator_rules.values():
            if not acc_rule.match_re:
                continue
            for source in acc_rule.source_filters:
                patterns_by_source.setdefault(source, {})[acc_rule.name] = acc_rule.match_re

        self.matcher = TwoStageSourceMatcher(patterns_by_source)
        self._ensure_filters_sorted()
        self._ensure_refiners_sorted()

    def _ensure_filters_sorted(self) -> None:
        """Sort filter execution order and build phase buckets for efficient dispatch."""
        if not self._filters_sorted:
            self._filter_execution_order.sort()
            self._filters_by_phase = {
                priority: [proc for _, _, proc in group]
                for priority, group in groupby(
                    self._filter_execution_order,
                    key=lambda x: x[0],
                )
            }
            self._filters_sorted = True

    def _ensure_refiners_sorted(self) -> None:
        """Sort refiner execution order and build phase buckets for efficient dispatch."""
        if not self._refiners_sorted:
            self._refiner_execution_order.sort()
            self._refiners_by_phase = {
                priority: [(entry.name, entry.processor) for entry in group]
                for priority, group in groupby(
                    self._refiner_execution_order,
                    key=lambda x: x.priority,
                )
            }
            self._refiners_sorted = True

    def process_event_filters(
        self,
        event_stream: EventStream,
        job_info: JobInfo,
        *,
        phase: Optional[int] = None,
    ) -> None:
        """Process filter rules in priority order (lower priority values first).

        Args:
            phase: If set, run only filters at this exact priority.
                   If None, run all filter phases in order.
        """
        self._ensure_filters_sorted()
        context = FilterContext(job_info=job_info, event_stream=event_stream)
        if phase is not None:
            for processor in self._filters_by_phase.get(phase, []):
                processor(context)
        else:
            for priority in sorted(self._filters_by_phase.keys()):
                for processor in self._filters_by_phase[priority]:
                    processor(context)

    def process_refiner_rules(
        self,
        event_stream: EventStream,
        job_info: JobInfo,
        *,
        symptoms: Any,
        my_bad_nodes: Any,
        raw_keywords: Optional[Any] = None,
        extract_job_metadata_from_logfile: bool = False,
        phase: Optional[int] = None,
        outcome: Optional[Any] = None,
        cancelled_by: Optional[str] = None,
        attribution_result: Optional[Any] = None,
        bad_node_result: Optional[Any] = None,
        recorder: Optional[DecisionRecorder] = None,
    ) -> RefinerContext:
        """Process refiner rules in priority order (lower priority values first).

        Args:
            event_stream: Event stream (for non-attribution queries, e.g. timeout).
            job_info: Job metadata.
            symptoms: Materialized SymptomSet[str].
            my_bad_nodes: Materialized JobNodeAttributions.
            raw_keywords: Raw keyword SymptomSet[str] from log scanning.
            extract_job_metadata_from_logfile: Whether job metadata was extracted from log file.
            phase: Run only refiners in this phase. The upper bound is derived
                   automatically from the next FilterPriority value.
                   If None, run all pre-outcome phases (SCRUB + FINAL).
            outcome: SourceSet[OutcomeAttribution] (for POST_OUTCOME refiners).
            cancelled_by: Cancellation source (for POST_OUTCOME refiners).
            attribution_result: AttributionResult (for POST_OUTCOME refiners).
            bad_node_result: CalcBadNodesAttributionResult (for POST_OUTCOME refiners).
            recorder: Optional DecisionRecorder for decision graph.

        Returns:
            The RefinerContext after all rules have executed.
        """
        self._ensure_refiners_sorted()
        context = RefinerContext(
            job_info=job_info,
            event_stream=event_stream,
            symptoms=symptoms,
            my_bad_nodes=my_bad_nodes,
            raw_keywords=raw_keywords,
            extract_job_metadata_from_logfile=extract_job_metadata_from_logfile,
            recorder=recorder,
            outcome=outcome,
            cancelled_by=cancelled_by,
            attribution_result=attribution_result,
            bad_node_result=bad_node_result,
        )

        def _run_refiners(phase_rules: list[tuple[str, "RefinerProcessor"]]) -> None:
            cached_bad: Optional[NodeSymptomSnapshot] = None
            for name, processor in phase_rules:
                before: Optional[set[str]] = None
                if recorder is not None:
                    before = set(symptoms.symptoms()) if symptoms is not None else set()
                    if cached_bad is None:
                        cached_bad = snapshot_bad_nodes(my_bad_nodes)
                processor(context)
                if recorder is not None and before is not None:
                    after = set(symptoms.symptoms()) if symptoms is not None else set()
                    after_bad = snapshot_bad_nodes(my_bad_nodes)
                    if after != before or after_bad != cached_bad:
                        recorder.record_refiner_diff(name, before, after, cached_bad or {}, after_bad)
                    cached_bad = after_bad

        if phase is not None:
            upper = min((p for p in FilterPriority if p > phase), default=None)
            for priority in sorted(self._refiners_by_phase.keys()):
                if priority < phase:
                    continue
                if upper is not None and priority >= upper:
                    break
                _run_refiners(self._refiners_by_phase[priority])
        else:
            for priority in sorted(self._refiners_by_phase.keys()):
                if priority >= FilterPriority.POST_OUTCOME:
                    break
                _run_refiners(self._refiners_by_phase[priority])
        return context

    def observation_processor(
        self,
        source_type: ObservationSource,
        job_info: JobInfo,
        event_stream: EventStream,
    ) -> "ObservationProcessor":
        """Create an ObservationProcessor for the given source type.

        Ensures the matcher is built before creating the processor.
        """
        if self.matcher is None:
            self.finalize()
        return ObservationProcessor(
            engine=self,
            source_type=source_type,
            context=RuleContext(job_info=job_info),
            event_adder=event_stream.event_adder(),
        )

    @contextmanager
    def _load_guard(self) -> Generator[None, None, None]:
        """Snapshot all load-mutable engine state; restore on any exception."""
        snap = _LoadSnapshot.capture(self)
        try:
            yield
        except Exception:
            snap.restore(self)
            raise

    def load(self, filepath: str | Path) -> dict[RuleId, Rule]:
        """
        Load a rules module and return dict of Rule objects.

        The rule file's parent directory is temporarily added to sys.path
        so that rule modules can import from sibling packages (e.g.
        ``from common.syslog_helpers import ...``).
        """
        path = Path(filepath)
        if path.suffix == ".toml":
            with self._load_guard(), _using_rules_engine(self):
                return load_toml_rules(self, str(path))

        rules_before = set(self.rules)
        with self._load_guard(), _using_rules_engine(self):
            spec = importlib.util.spec_from_file_location("rules_module", str(path))
            if spec is None or spec.loader is None:
                raise RuleIngestionError(f"Cannot load module from {path}")

            module = importlib.util.module_from_spec(spec)

            # Temporarily add rule file's parent directory to sys.path so
            # rules can import from sibling packages (e.g. common/).
            parent_dir = str(path.resolve().parent)
            sys_path_snapshot = sys.path.copy()
            sys.path.insert(0, parent_dir)

            try:
                with _using_module_globals(module.__dict__):
                    spec.loader.exec_module(module)
            finally:
                sys.path[:] = sys_path_snapshot

            # Return only the rules that were added by this module
            return {name: rule for name, rule in self.rules.items() if name not in rules_before}

    def extractor_hash(self) -> str:
        """Stable hash of all extractor rules. Changes when extraction behavior changes.

        TODO: evolve into a versioned scheme that can detect compatible vs breaking
        rule changes (e.g. additive rules could reuse existing cache + incremental extract).
        """
        h = hashlib.sha256()
        for name in sorted(self.extractor_rules):
            rule = self.extractor_rules[name]
            h.update(name.encode())
            h.update(rule.match_re.encode())
            h.update(str(sorted(sf.value for sf in rule.source_filters)).encode())
            h.update(self.declarative_emit.get(name, "").encode())
        for name in sorted(self.extractor_accumulator_rules):
            acc_rule = self.extractor_accumulator_rules[name]
            h.update(name.encode())
            h.update(acc_rule.match_re.encode())
        return h.hexdigest()

    def attribution_hash(self) -> str:
        """Stable hash of filter/refiner/collector rules. Changes when attribution logic changes."""
        h = hashlib.sha256()
        for name in sorted(self.filter_rules):
            filter_rule = self.filter_rules[name]
            h.update(name.encode())
            h.update(str(filter_rule.priority).encode())
        for name in sorted(self.refiner_rules):
            refiner_rule = self.refiner_rules[name]
            h.update(name.encode())
            h.update(str(refiner_rule.priority).encode())
        for name in sorted(self.collector_rules):
            h.update(name.encode())
        return h.hexdigest()


@dataclass(frozen=True, slots=True)
class SourceProcessingConfig:
    """Per-source-type configuration for process_observation_source."""

    time_start: Optional[Callable[[JobInfo], Optional[datetime]]] = None
    time_end: Optional[Callable[[JobInfo], Optional[datetime]]] = None
    fallback_unknown_nodes: bool = False
    requires_nodes: bool = False


# Populated by core.py via register_source_config(); keeps rules_engine
# free of source-specific imports.
SOURCE_CONFIGS: dict[ObservationSource, SourceProcessingConfig] = {}


def register_source_config(source: ObservationSource, config: SourceProcessingConfig) -> None:
    """Register processing configuration for an observation source type."""
    SOURCE_CONFIGS[source] = config


def _apply_pre_filter(
    entry: EntryProtocol,
    job_info: JobInfo,
    exclude_set: Optional[set[str]],
    include_set: Optional[set[str]],
    callables: Optional[list[PreFilterCallable]],
) -> tuple[bool, list[str]]:
    """Apply pre-filter logic to a single entry.

    Returns (skip, keywords) where skip=True means the entry should be
    discarded, and keywords is a list of matched include terms or
    callable-contributed keywords to add to raw_keywords.
    """
    body = entry.body()
    skip = False
    keywords: list[str] = []

    # 1. Callable pre-filters run first — they can collect keywords
    #    from entries that will later be excluded by keyword rules.
    if callables:
        for fn in callables:
            result = fn(entry, job_info)
            if isinstance(result, tuple):
                should_skip, kw = result
                keywords.extend(kw)
                if should_skip:
                    skip = True
            elif result:
                skip = True

    if skip:
        return True, keywords

    # 2. Keyword exclude
    if exclude_set:
        for term in exclude_set:
            if term in body:
                return True, keywords

    # 3. Keyword include — collect matched terms
    if include_set:
        for term in include_set:
            if term in body:
                keywords.append(term)

    return False, keywords


def process_observation_source(
    *,
    event_stream: EventStream,
    observation_source: EntrySourceBase,
    job_info: JobInfo,
    rules_engine: RuleEngine,
    pre_filtered: bool,
) -> set[str]:
    """Process an observation source through the rules engine.

    Args:
        pre_filtered: If True, skip all pre-filter logic (keyword exclude/include
            and callables). Caller is responsible for any filtering.

    Returns:
        Set of content-derived raw_keywords collected from include term matches
        and callable pre-filter returns. Empty if pre_filtered=True.
    """
    source_type = observation_source.context.source
    config = SOURCE_CONFIGS.get(source_type)
    time_start = config.time_start(job_info) if config and config.time_start else None
    time_end = config.time_end(job_info) if config and config.time_end else None
    fallback_unknown_nodes = config.fallback_unknown_nodes if config else False

    raw_keywords: set[str] = set()

    # Build pre-filter state (once, not per-entry)
    pre_filter_spec = None if pre_filtered else _PRE_FILTERS.get(source_type)
    exclude_set = set(pre_filter_spec.exclude_terms) if pre_filter_spec else None
    include_set = set(pre_filter_spec.include_terms) if pre_filter_spec else None
    pf_callables = pre_filter_spec.callables if pre_filter_spec else None

    processor = rules_engine.observation_processor(source_type, job_info, event_stream)

    for entry in iter(observation_source):
        # Pre-filter phase (when not pre_filtered)
        if pre_filter_spec is not None:
            skip, entry_keywords = _apply_pre_filter(entry, job_info, exclude_set, include_set, pf_callables)
            raw_keywords.update(entry_keywords)
            if skip:
                continue

        # Time filtering
        if time_start is not None or time_end is not None:
            entry_time = entry.time()
            if time_start is not None and entry_time < time_start:
                log_ignored_time_line(entry, job_info, "before_start", entry.context().source)
                continue
            if time_end is not None and entry_time > time_end:
                log_ignored_time_line(entry, job_info, "after_end", entry.context().source)
                continue

        # Node resolution and source building
        if fallback_unknown_nodes:
            try:
                att_src_base = entry.attribution_source_base(job_info)
            except UnknownResourceError as e:
                log_ignored_node_line(e, entry, job_info, entry.context().source)
                att_src_base = entry.attribution_source_base(None)
        else:
            try:
                node = entry.node(job_info)
            except UnknownResourceError as e:
                log_ignored_node_line(e, entry, job_info, entry.context().source)
                continue

            if not node:
                continue

            att_src_base = entry.attribution_source_base(job_info)

        processor.process_line(att_src_base)

    processor.finalize()
    return raw_keywords


__all__ = [
    # Rule types and the accumulator protocol
    "CollectorRule",
    "ExtractorAccumulator",
    "ExtractorAccumulatorRule",
    "ExtractorRule",
    "FilterRule",
    "RefinerRule",
    "Rule",
    # Execution contexts
    "CollectorContext",
    "ExecutionContext",
    "ExtractionContext",
    "FilterContext",
    "RefinerContext",
    "RuleContext",
    # Values a rule file declares or receives
    "EventTriple",
    "FilterPriority",
    "RuleId",
    "RuleLocation",
    "RuleParameters",
    "RuleParamsBase",
    # Processor and formatter signatures
    "CollectorFormatter",
    "CollectorProcessor",
    "ExtractorProcessor",
    "FilterProcessor",
    "RefinerProcessor",
    # Rule registration
    "collector_def",
    "declare_event_types",
    "declare_rule_names",
    "extractor_accumulator_def",
    "filter_def",
    "normalize_tags",
    "refiner_def",
    # Declarative (TOML) registration
    "EXPR_HELPER_INJECTED_PARAMS",
    "const",
    "expr_helper",
    "rows",
    "rule_processor",
    # Symptom declaration
    "cascade_symptom",
    "known_symptom",
    "outcome_symptom",
    "symptom_predicate",
    # Pre-filter, metric and source configuration
    "MetricSpec",
    "PreFilterCallable",
    "PreFilterSpec",
    "SOURCE_CONFIGS",
    "SourceProcessingConfig",
    "get_metric_spec",
    "get_pre_filter",
    "register_metric_spec",
    "register_pre_filter",
    "register_source_config",
    # Engine and execution
    "ObservationProcessor",
    "RuleEngine",
    "TwoStageSourceMatcher",
    "process_observation_source",
    # Compatibility exports owned by exceptions and symptoms.declarations.
    "CascadeScope",
    "DagDiscardBehavior",
    "DuplicateRuleError",
    "OutcomePriority",
    "RuleIngestionError",
    "SymptomCategory",
    "SymptomDeclaration",
    "SymptomPredicate",
]
