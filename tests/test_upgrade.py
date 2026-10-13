"""The upgrade path must not lose local work.

scripts/upgrade.py reads the repository with git and decides whether it can
fast-forward. Both halves are easy to get subtly wrong: parsing `git status
--porcelain` by byte offset silently loses a character (it did - _git strips
trailing whitespace, which eats the leading space of the first line), and the
overlap check exists so that a local edit is reported *before* the merge is
attempted, not after git has refused it.
"""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import upgrade  # noqa: E402


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def init_repo(path: Path) -> Path:
    git("init", "-q", cwd=path)
    git("config", "core.autocrlf", "false", cwd=path)
    git("config", "user.email", "test@example.com", cwd=path)
    git("config", "user.name", "Test", cwd=path)
    return path


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A one-commit repository that upgrade.py has been pointed at."""
    init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("one\n")
    git("add", "-A", cwd=tmp_path)
    git("commit", "-qm", "init", cwd=tmp_path)
    monkeypatch.setattr(upgrade, "ROOT", tmp_path)
    return tmp_path


@pytest.fixture
def behind(tmp_path, monkeypatch):
    """A clone sitting one commit behind its origin, which is a local bare repo.

    Returns (clone, path-of-the-file-the-missing-commit-changes).
    """
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)

    seed = tmp_path / "seed"
    seed.mkdir()
    init_repo(seed)
    (seed / "a.txt").write_text("one\n")
    (seed / "b.txt").write_text("one\n")
    git("add", "-A", cwd=seed)
    git("commit", "-qm", "first", cwd=seed)
    git("push", "-q", str(remote), "HEAD:refs/heads/main", cwd=seed)
    git("symbolic-ref", "HEAD", "refs/heads/main", cwd=remote)

    (seed / "a.txt").write_text("two\n")
    git("commit", "-qam", "second", cwd=seed)
    git("push", "-q", str(remote), "HEAD:refs/heads/main", cwd=seed)

    clone = tmp_path / "clone"
    git("clone", "-q", str(remote), str(clone), cwd=tmp_path)
    git("reset", "--hard", "HEAD~1", cwd=clone)
    monkeypatch.setattr(upgrade, "ROOT", clone)
    return clone, "a.txt"


class TestModifiedFiles:
    def test_clean_tree_has_no_local_changes(self, repo):
        assert upgrade._modified_files() == set()

    def test_a_modified_file_is_reported_by_its_exact_path(self, repo):
        (repo / "a.txt").write_text("two\n")
        assert upgrade._modified_files() == {"a.txt"}

    def test_untracked_files_count_as_local_changes(self, repo):
        (repo / "fresh.txt").write_text("new\n")
        assert upgrade._modified_files() == {"fresh.txt"}

    def test_the_first_path_is_not_truncated(self, repo):
        # The old porcelain parse returned ".txt" here: it sliced three
        # characters off a line that had already lost its leading space.
        (repo / "a.txt").write_text("two\n")
        (repo / "b.txt").write_text("fresh\n")
        assert upgrade._modified_files() == {"a.txt", "b.txt"}


class TestUpgradeDecision:
    def test_a_clash_is_reported_before_anything_is_touched(self, behind, capsys):
        clone, clashing = behind
        (clone / clashing).write_text("local edit\n")
        before = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(clone),
                                check=True, capture_output=True, text=True).stdout

        assert upgrade.main() == 2

        assert clashing in capsys.readouterr().out
        assert (clone / clashing).read_text() == "local edit\n"
        after = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(clone),
                               check=True, capture_output=True, text=True).stdout
        assert after == before

    def test_an_unrelated_local_edit_does_not_block_the_fast_forward(self, behind, capsys):
        clone, _clashing = behind
        (clone / "b.txt").write_text("local edit\n")

        assert upgrade.main() == 0

        assert (clone / "b.txt").read_text() == "local edit\n"
        head = subprocess.run(["git", "log", "-1", "--format=%s"], cwd=str(clone),
                              check=True, capture_output=True, text=True).stdout
        assert head.strip() == "second"
        assert "已升级" in capsys.readouterr().out

    def test_a_checkout_without_an_upstream_is_reported(self, repo, monkeypatch, capsys):
        monkeypatch.setattr(upgrade, "_upstream", lambda: "")
        assert upgrade.main() == 2
        assert "没有绑定远端分支" in capsys.readouterr().out

    def test_a_second_run_has_nothing_left_to_do(self, behind, capsys):
        assert upgrade.main() == 0
        capsys.readouterr()
        assert upgrade.main() == 0
        assert "已是最新版本" in capsys.readouterr().out
