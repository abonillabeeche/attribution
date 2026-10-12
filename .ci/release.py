# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# /// script
# requires-python = ">=3.11"
# dependencies = ["packaging>=24"]
# ///
"""Advisory release status for the components in this repository.

Read-only; needs a full clone with tags. One subcommand:

    status  per component: version literal, latest tag (any / stable-only),
            first-parent distance since that tag, PRs merged since.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional

from release_git import (
    COMPONENTS,
    RELEASABLE,
    ReleaseError,
    TagInfo,
    default_repo,
    git,
    tag_for,
)
from release_rules import ComponentStatus, is_release_pr, releasing_components


RELEASE_PR_RULE = (
    "Release PR: any component's literal differs from the base; a component is "
    "releasing when its own literal changed and did not decrease."
)
DISTANCE_RULE = (
    "Distance counts first-parent commits since the tag over the component and "
    "its in-repo dependencies; the shortlog covers the component's own path only."
)


def _release_pr_line(statuses: dict[str, ComponentStatus]) -> str:
    if not is_release_pr(statuses):
        return "not a release PR, nothing releasing"
    names = [name for name, s in statuses.items() if s.releasing]
    return "release PR: releasing " + (", ".join(names) if names else "none")


def _yes_no(flag: bool) -> str:
    return "yes" if flag else "no"


def _tag_cells(info: Optional[TagInfo]) -> tuple[str, str]:
    if info is None:
        return "unreleased", "unreleased"
    return info.tag, str(info.distance)


def render_status(repo: Path, statuses: dict[str, ComponentStatus]) -> str:
    lines = [
        _release_pr_line(statuses),
        "",
        "| component | literal | base literal | latest-any | distance-any "
        "| latest-stable | distance-stable | releasing? | pre-release? |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for name, s in statuses.items():
        any_tag, any_distance = _tag_cells(s.latest.any)
        stable_tag, stable_distance = _tag_cells(s.latest.stable)
        lines.append(
            f"| {name} | {s.literal} | {s.base_literal or '-'} | {any_tag} "
            f"| {any_distance} | {stable_tag} | {stable_distance} "
            f"| {_yes_no(s.releasing)} | {_yes_no(s.is_prerelease)} |"
        )
    lines.append("")
    for name, s in statuses.items():
        if s.decreased:
            lines.append(
                f"{name}: literal decreased relative to base; not releasing, "
                "the tag job will not tag"
            )
        if s.releasing and RELEASABLE.match(s.literal):
            lines.append(f"{name}: planned tag {tag_for(name, s.literal)}")
    for name, s in statuses.items():
        since = s.latest.any.tag if s.latest.any is not None else None
        rev_range = f"{since}..HEAD" if since is not None else "HEAD"
        shortlog = git(
            repo, "shortlog", "--first-parent", rev_range, "--", COMPONENTS[name].path
        ).rstrip()
        lines += [
            "",
            f"### {name}: PRs since {since or 'start of history'}",
            "",
            "```",
            shortlog or "(none)",
            "```",
        ]
    lines += ["", DISTANCE_RULE, RELEASE_PR_RULE]
    return "\n".join(lines)


def _emit(text: str) -> None:
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as handle:
            handle.write(text + "\n")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command, help_text in (
        ("status", "print literals, latest tags, distance and shortlogs"),
    ):
        sub = subparsers.add_parser(command, help=help_text)
        sub.add_argument(
            "--base",
            default="origin/main",
            help="ref whose merge-base with HEAD the literals are compared against",
        )
        sub.add_argument("--repo", type=Path, default=None, help="repository root")
    args = parser.parse_args(argv)

    try:
        repo = args.repo if args.repo is not None else default_repo()
        statuses = releasing_components(repo, args.base)
        report = render_status(repo, statuses)
    except ReleaseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    _emit(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
