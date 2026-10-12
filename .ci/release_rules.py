# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Per-component release status - checks if this is a release PR."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from release_git import (
    COMPONENTS,
    LatestTags,
    ReleaseError,
    git,
    latest_tags,
    parse_version,
    read_literal,
)


@dataclass(frozen=True)
class ComponentStatus:
    name: str
    """Component name like "service-app"."""
    literal: str
    """The committed version literal."""
    base_literal: Optional[str]
    """The committed version literal at `base`, or None if the component did not exist yet."""
    latest: LatestTags
    """Latest tags, any and stable."""
    releasing: bool
    """The literal changed and did not decrease relative to `base`."""
    is_prerelease: bool
    """The new literal is a release candidate (e.g. X.Y.ZrcN)."""
    decreased: bool
    """The new literal went below the `base` literal: advisory, never releasing."""


def releasing_components(repo: Path, base: Optional[str]) -> dict[str, ComponentStatus]:
    """Per-component status against `base`; a release PR is one where some literal changed.

    Literals are compared at the merge-base of `base` and HEAD, so a branch that has
    not been rebased does not report main's later literal changes as its own.
    """
    if base is not None:
        base = git(repo, "merge-base", base, "HEAD").strip()
    statuses: dict[str, ComponentStatus] = {}
    for name, comp in COMPONENTS.items():
        literal = read_literal(repo, comp, None)
        if literal is None:
            raise ReleaseError(f"{comp.literal_file}: no __version__ literal")
        base_literal = read_literal(repo, comp, base) if base is not None else None
        changed = base_literal is not None and literal != base_literal
        new_version = parse_version(literal)
        old_version = parse_version(base_literal)
        decreased = (
            changed
            and new_version is not None
            and old_version is not None
            and new_version < old_version
        )
        latest = latest_tags(repo, name)
        statuses[name] = ComponentStatus(
            name=name,
            literal=literal,
            base_literal=base_literal,
            latest=latest,
            releasing=changed and not decreased,
            is_prerelease=(
                new_version is not None
                and new_version.pre is not None
                and new_version.pre[0] == "rc"
            ),
            decreased=decreased,
        )
    return statuses


def is_release_pr(statuses: dict[str, ComponentStatus]) -> bool:
    """True iff some component's literal differs from the base, up or down.

    A decrease alone still makes it a release PR, but releases nothing.
    """
    return any(s.releasing or s.decreased for s in statuses.values())
