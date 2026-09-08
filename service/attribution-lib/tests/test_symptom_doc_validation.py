# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for symptom-to-documentation resolution."""

from attribution_lib.symptoms.declarations import SymptomDeclaration
from attribution_lib.symptoms.doc_validation import (
    build_doc_name_index,
    find_undeclared_symptom_names,
    find_unresolved_symptom_docs,
    normalize_symptom_name,
    stale_baseline_entries,
    symptom_requires_doc,
)

# The published slugs a symptom's doc must resolve against (stand-in for url-map.json ids).
VALID_DOC_IDS = {"xid-48", "oom-kill-of-user-task"}


def _symptom(prefix, *, outcome="Fail InfraHW", doc="xid-48", cascade_noop=False, fallback_prefix=False):
    return SymptomDeclaration(
        prefix=prefix,
        outcome=outcome,
        doc=doc,
        cascade_noop=cascade_noop,
        fallback_prefix=fallback_prefix,
    )


class TestSymptomRequiresDoc:
    def test_outcome_bearing_symptom_requires_doc(self):
        assert symptom_requires_doc(_symptom("XID-48")) is True

    def test_cascade_only_declaration_is_exempt(self):
        # Cascade-only declarations describe pruning edges, not user-facing symptoms.
        assert symptom_requires_doc(_symptom("cascade", outcome=None, cascade_noop=True)) is False

    def test_generic_fallback_prefix_is_exempt(self):
        # Dynamic families like "XID-" resolve raw ids at runtime and have no single doc.
        assert symptom_requires_doc(_symptom("XID-", fallback_prefix=True)) is False

    def test_declaration_without_outcome_is_exempt(self):
        assert symptom_requires_doc(_symptom("noop", outcome=None)) is False


class TestFindUnresolvedSymptomDocs:
    def test_resolving_slug_is_not_flagged(self):
        assert find_unresolved_symptom_docs([_symptom("XID-48", doc="xid-48")], VALID_DOC_IDS) == []

    def test_missing_doc_field_is_flagged(self):
        result = find_unresolved_symptom_docs([_symptom("XID-99", doc=None)], VALID_DOC_IDS)
        assert [d.prefix for d in result] == ["XID-99"]

    def test_empty_doc_string_is_flagged(self):
        result = find_unresolved_symptom_docs([_symptom("XID-99", doc="")], VALID_DOC_IDS)
        assert [d.prefix for d in result] == ["XID-99"]

    def test_unresolvable_slug_is_flagged(self):
        result = find_unresolved_symptom_docs([_symptom("kernel-oops", doc="kernel-oops")], VALID_DOC_IDS)
        assert [d.prefix for d in result] == ["kernel-oops"]

    def test_dynamic_and_cascade_symptoms_are_not_flagged(self):
        # Aaron's caveat: dynamic/generic symptoms must not be treated as missing docs.
        declarations = [
            _symptom("XID-", doc=None, fallback_prefix=True),
            _symptom("cascade", outcome=None, doc=None, cascade_noop=True),
        ]
        assert find_unresolved_symptom_docs(declarations, VALID_DOC_IDS) == []

    def test_baselined_declaration_pair_is_grandfathered(self):
        declarations = [_symptom("kernel-oops", doc="kernel-oops")]
        baseline = frozenset({("kernel-oops", "kernel-oops")})
        result = find_unresolved_symptom_docs(declarations, VALID_DOC_IDS, baseline=baseline)
        assert result == []

    def test_new_unresolved_still_flagged_despite_baseline(self):
        declarations = [
            _symptom("kernel-oops", doc="kernel-oops"),
            _symptom("brand-new", doc="brand-new"),
        ]
        baseline = frozenset({("kernel-oops", "kernel-oops")})
        result = find_unresolved_symptom_docs(declarations, VALID_DOC_IDS, baseline=baseline)
        assert [d.prefix for d in result] == ["brand-new"]

    def test_new_symptom_cannot_reuse_baselined_slug(self):
        declarations = [_symptom("Brand new symptom", doc="kernel-oops")]
        baseline = frozenset({("kernel-oops", "kernel-oops")})
        result = find_unresolved_symptom_docs(declarations, VALID_DOC_IDS, baseline=baseline)
        assert [d.prefix for d in result] == ["Brand new symptom"]


class TestStaleBaselineEntries:
    def test_baseline_pair_that_now_resolves_is_reported(self):
        declarations = [_symptom("oom", doc="oom-kill-of-user-task")]
        baseline = frozenset({("oom", "oom-kill-of-user-task")})
        stale = stale_baseline_entries(declarations, VALID_DOC_IDS, baseline)
        assert stale == [("oom", "oom-kill-of-user-task")]

    def test_still_missing_baseline_pair_is_not_stale(self):
        declarations = [_symptom("kernel-oops", doc="kernel-oops")]
        baseline = frozenset({("kernel-oops", "kernel-oops")})
        stale = stale_baseline_entries(declarations, VALID_DOC_IDS, baseline)
        assert stale == []

    def test_baseline_pair_is_stale_when_declaration_disappears(self):
        baseline = frozenset({("retired-symptom", "retired-symptom")})
        assert stale_baseline_entries([], VALID_DOC_IDS, baseline) == [("retired-symptom", "retired-symptom")]


def _name_index(*, aliases: list[str] | None = None) -> dict[str, frozenset[str]]:
    return build_doc_name_index(
        [
            {
                "id": "not-responding",
                "title": "Not responding",
                "aliases": aliases or [],
                "redirect_ids": [],
            }
        ]
    )


class TestSymptomNameDeclarations:
    def test_normalization_ignores_case_whitespace_and_punctuation(self):
        assert normalize_symptom_name(" XID 48 / DBE ") == "xid-48-dbe"

    def test_canonical_document_name_passes(self):
        assert find_undeclared_symptom_names([_symptom("Not responding", doc="not-responding")], _name_index()) == []

    def test_declared_alias_passes(self):
        declarations = [_symptom("Corroborated node failure", doc="not-responding")]
        assert (
            find_undeclared_symptom_names(
                declarations,
                _name_index(aliases=["Corroborated node failure"]),
            )
            == []
        )

    def test_existing_but_undeclared_document_is_flagged(self):
        declarations = [_symptom("Corroborated node failure", doc="not-responding")]
        assert find_undeclared_symptom_names(declarations, _name_index()) == declarations

    def test_dynamic_fallback_is_exempt(self):
        declarations = [_symptom("XID-", doc="not-responding", fallback_prefix=True)]
        assert find_undeclared_symptom_names(declarations, _name_index()) == []

    def test_redirect_inherits_target_names(self):
        index = build_doc_name_index(
            [
                {
                    "id": "xid-48",
                    "title": "XID 48",
                    "aliases": [],
                    "redirect_ids": ["xid-48-gpu-ecc-dbe"],
                }
            ]
        )
        assert (
            find_undeclared_symptom_names(
                [_symptom("XID-48", doc="xid-48-gpu-ecc-dbe")],
                index,
            )
            == []
        )
