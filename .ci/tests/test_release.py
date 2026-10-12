# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # .ci/ is not a package
import release  # noqa: E402
import release_git  # noqa: E402
import release_rules  # noqa: E402

INTERIM = {
    "attribution-lib": "0.4.0",
    "service-app": "1.0.0",
    "blueprint": "0.1.0",
}


@dataclass
class Repo:
    path: Path

    def git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.path, check=True, capture_output=True)

    def write(self, relpath: str, text: str) -> None:
        target = self.path / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def commit(self, msg: str) -> None:
        self.git("add", "-A")
        self.git("commit", "-m", msg)

    def tag(self, name: str) -> None:
        self.git("tag", "-a", name, "-m", name)

    def mark_base(self) -> None:
        self.git("branch", "-f", "base")

    def set_literal(self, component: str, value: str) -> None:
        self.write(
            release_git.COMPONENTS[component].literal_file, f'__version__ = "{value}"\n'
        )

    def statuses(self) -> dict[str, release_rules.ComponentStatus]:
        return release_rules.releasing_components(self.path, "base")


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    r = Repo(tmp_path)
    r.git("init", "-b", "main")
    for key, value in (
        ("user.name", "tests"),
        ("user.email", "tests@example.com"),
        ("commit.gpgsign", "false"),
        ("tag.gpgsign", "false"),
    ):
        r.git("config", key, value)
    for component, literal in INTERIM.items():
        r.set_literal(component, literal)
    r.write("docs/x", "")
    r.commit("initial")
    r.mark_base()
    return r


def test_unchanged_literals_are_not_a_release_pr(repo: Repo) -> None:
    statuses = repo.statuses()

    assert release._release_pr_line(statuses) == "not a release PR, nothing releasing"
    assert not any(s.releasing for s in statuses.values())


def test_only_bumped_component_releases_and_a_decrease_never_does(repo: Repo) -> None:
    repo.set_literal("attribution-lib", "0.5.0")
    repo.commit("bump lib")
    statuses = repo.statuses()
    assert statuses["attribution-lib"].releasing
    assert not statuses["service-app"].releasing

    repo.set_literal("attribution-lib", "0.3.0")
    repo.commit("lower lib")
    statuses = repo.statuses()
    assert not statuses["attribution-lib"].releasing
    assert statuses["attribution-lib"].decreased


def test_literals_are_compared_at_the_merge_base_not_the_tip_of_base(
    repo: Repo,
) -> None:
    repo.git("checkout", "-b", "stale")
    repo.write("docs/y", "")
    repo.commit("unrelated")
    repo.git("checkout", "main")
    repo.set_literal("attribution-lib", "0.5.0")
    repo.commit("bump lib on main")
    repo.git("checkout", "stale")

    statuses = release_rules.releasing_components(repo.path, "main")
    assert not statuses["attribution-lib"].releasing
    assert not statuses["attribution-lib"].decreased


def test_only_an_rc_literal_is_a_prerelease(repo: Repo) -> None:
    repo.set_literal("service-app", "2.0.0.dev0")
    repo.set_literal("blueprint", "0.2.0rc1")
    repo.commit("dev and rc")
    statuses = repo.statuses()
    assert not statuses["service-app"].is_prerelease
    assert statuses["blueprint"].is_prerelease


def test_distance_counts_first_parent_commits_in_the_closure_only(repo: Repo) -> None:
    repo.tag("service-app-v2.0.0")
    repo.git("checkout", "-b", "side")
    for i in range(3):
        repo.write(f"service/attribution-lib/side{i}", "")
        repo.commit(f"side {i}")
    repo.git("checkout", "main")
    repo.git("merge", "--no-ff", "-m", "merge", "side")
    assert release_git.distance(repo.path, "service-app", "service-app-v2.0.0") == 1

    repo.write("docs/y", "")
    repo.commit("docs")
    assert release_git.distance(repo.path, "service-app", "service-app-v2.0.0") == 1

    repo.write("blueprint/x", "")
    repo.commit("blueprint")
    assert release_git.distance(repo.path, "service-app", "service-app-v2.0.0") == 1


def test_tag_names_round_trip_and_releasable_shapes() -> None:
    for literal, tag in (
        ("2.0.0", "service-app-v2.0.0"),
        ("2.0.0rc1", "service-app-v2.0.0-rc.1"),
    ):
        assert release_git.tag_for("service-app", literal) == tag
        assert str(release_git.version_from_tag("service-app", tag)) == literal
    assert all(release_git.RELEASABLE.match(v) for v in ("2.0.0", "2.0.0rc1"))
    assert not any(
        release_git.RELEASABLE.match(v) for v in ("2.0.0.dev0", "2.0.0+1", "2.0.0a1")
    )
    for literal in ("2.0.0.dev0", "2.0.0a1"):
        with pytest.raises(release_git.ReleaseError):
            release_git.tag_for("service-app", literal)
