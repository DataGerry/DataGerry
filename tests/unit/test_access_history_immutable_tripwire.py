# DataGerry - OpenSource Enterprise CMDB
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
Tripwire: nothing in ``cmdb/`` changes or removes an access history entry

The history is insert-only: a call updating, replacing, deleting or dropping on anything named after the history is
refused everywhere but in its manager (the retention's TTL index). A write ledger undoing a failed request's entries
does so through its generic undo, which names no history
"""
import ast
from pathlib import Path

import pytest
# -------------------------------------------------------------------------------------------------------------------- #

CMDB_ROOT: Path = Path(__file__).resolve().parents[2] / 'cmdb'
ALLOWED_FILE: str = 'manager/access_history_manager.py'
CHANGING_PREFIXES: tuple[str, ...] = ('update', 'replace', 'delete', 'drop', 'remove', 'find_one_and')
HISTORY_MARKER: str = 'history'
ACCESS_MARKER: str = 'access'


def _offences(path: Path) -> list[str]:
    """The changing calls on a receiver named after the access history"""
    offences: list[str] = []

    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue

        receiver: str = ast.unparse(node.func.value).lower()

        if HISTORY_MARKER in receiver and node.func.attr.startswith(CHANGING_PREFIXES) and (
                ACCESS_MARKER in receiver or receiver == HISTORY_MARKER):
            offences.append(f'{path.relative_to(CMDB_ROOT)}:{node.lineno} {ast.unparse(node.func)}')

    return offences


FILES: list[Path] = sorted(path for path in CMDB_ROOT.rglob('*.py')
                           if path.relative_to(CMDB_ROOT).as_posix() != ALLOWED_FILE)


@pytest.mark.parametrize('path', FILES, ids=lambda path: path.relative_to(CMDB_ROOT).as_posix())
def test_no_history_entry_is_changed(path: Path) -> None:
    """Insert and read only"""
    assert _offences(path) == []


def test_the_census_is_not_empty() -> None:
    """A moved folder must not make the check vacuous"""
    assert len(FILES) > 100
