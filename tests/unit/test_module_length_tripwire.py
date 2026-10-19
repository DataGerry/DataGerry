# DATAGERRY - OpenSource Enterprise CMDB
# Copyright (C) 2026 becon GmbH
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""
Tripwire: no module of the cmdb/ tree is longer than pylint's module-length limit

CI's lint gate is a score, so pylint's ``too-many-lines`` (C0302) only lowers it and never fails a build - a module
grows past ``max-module-lines`` unnoticed. This scan makes crossing the limit a failing test. The limit is read from
.pylintrc, and the lines are counted the way pylint counts them: every line of the file.

A module already over the limit is listed in ``KNOWN_OVER_LIMIT`` with the length it had when it was listed. It may
shrink but not grow, and once it is back under the limit the entry must go - a stale entry fails too. The list is
empty
"""
from pathlib import Path

import pytest

from tests.utils.pylint_limits import REPO_ROOT, pylint_limit
# -------------------------------------------------------------------------------------------------------------------- #

CMDB_ROOT: Path = REPO_ROOT / 'cmdb'
MODULE_LINES_OPTION: str = 'max-module-lines'

# The smallest tree the scan must still cover, so a moved package cannot make it pass vacuously
MIN_SCANNED_MODULES: int = 1000

# Modules over the limit that are still to be split, by path relative to cmdb/, with their length when listed
KNOWN_OVER_LIMIT: dict[str, int] = {}


def module_lines(path: Path) -> int:
    """
    Counts a module's lines the way pylint's too-many-lines does

    Args:
        path (Path): The module

    Returns:
        int: Its number of lines
    """
    return len(path.read_text(encoding='utf-8').splitlines())


def modules_over_limit(root: Path, limit: int) -> dict[str, int]:
    """
    Answers every module under a tree that is longer than a limit

    Args:
        root (Path): The tree to scan
        limit (int): The longest a module may be

    Returns:
        dict[str, int]: Each module over the limit, by its path relative to `root`, with its length
    """
    return {
        path.relative_to(root).as_posix(): lines
        for path in sorted(root.rglob('*.py'))
        if (lines := module_lines(path)) > limit
    }


def test_no_module_is_newly_over_the_limit() -> None:
    """A module not listed as a known exception stays within max-module-lines"""
    over: dict[str, int] = modules_over_limit(CMDB_ROOT, pylint_limit(MODULE_LINES_OPTION))

    assert {path: lines for path, lines in over.items() if path not in KNOWN_OVER_LIMIT} == {}


@pytest.mark.parametrize('module, listed_lines', KNOWN_OVER_LIMIT.items())
def test_a_known_exception_does_not_grow(module: str, listed_lines: int) -> None:
    """It may only shrink until it is split"""
    assert module_lines(CMDB_ROOT / module) <= listed_lines


@pytest.mark.parametrize('module', KNOWN_OVER_LIMIT)
def test_a_known_exception_is_still_over_the_limit(module: str) -> None:
    """One back under the limit is taken off the list, so the list never hides a module that grows again"""
    assert module_lines(CMDB_ROOT / module) > pylint_limit(MODULE_LINES_OPTION)


def test_the_scan_covers_the_tree() -> None:
    """A moved or renamed package cannot make the scan pass on nothing"""
    assert sum(1 for _ in CMDB_ROOT.rglob('*.py')) >= MIN_SCANNED_MODULES


class TestModulesOverLimit:
    """The scan itself, on a tree of its own"""

    LIMIT: int = 3

    @staticmethod
    def _module(root: Path, name: str, lines: int) -> None:
        """Writes a module of the given length"""
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(''.join(f'x_{line} = {line}\n' for line in range(lines)), encoding='utf-8')

    def test_only_a_module_past_the_limit_is_reported_with_its_length(self, tmp_path: Path) -> None:
        """At the limit passes, one line past it does not - in a nested package too"""
        self._module(tmp_path, 'at_limit.py', self.LIMIT)
        self._module(tmp_path, 'package/over_limit.py', self.LIMIT + 1)

        assert modules_over_limit(tmp_path, self.LIMIT) == {'package/over_limit.py': self.LIMIT + 1}

    def test_files_that_are_no_python_modules_are_ignored(self, tmp_path: Path) -> None:
        """A long template or data file is not pylint's to count"""
        self._module(tmp_path, 'notes.txt', self.LIMIT + 5)

        assert not modules_over_limit(tmp_path, self.LIMIT)

    def test_lines_are_counted_like_pylint_without_a_trailing_newline(self, tmp_path: Path) -> None:
        """The last line counts whether or not it ends in a newline"""
        path = tmp_path / 'no_newline.py'
        path.write_text('a = 1\nb = 2', encoding='utf-8')

        assert module_lines(path) == 2
