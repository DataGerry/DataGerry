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
Tripwire: nothing in ``cmdb/`` reads a single ``group_id`` attribute

A CmdbUser is a member of one or more groups (``group_ids``); its old single ``group_id`` is gone from the document,
the API and the model. A reader that took one group - the rights, the type ACL, a guard - would quietly judge a user
in several groups by one of them. The ``group_id`` attributes left name a group, not a user's membership: the group
delete's MOVE target (``GroupDeletionParameters.group_id``), read where the parameters are built and in the delete
route, and the one user group an access assignment grants (``CmdbAccessAssignment.group_id``).

Read with ``ast``, so every module is covered whether or not a test imports it. The migrations are left out: their
literals are frozen and they run on data stored before ``group_ids``.
"""
import ast
from pathlib import Path

import pytest
# -------------------------------------------------------------------------------------------------------------------- #

CMDB_ROOT: Path = Path(__file__).resolve().parents[2] / 'cmdb'
MIGRATIONS_DIR: str = 'updater'
SINGLE_GROUP_ATTRIBUTE: str = 'group_id'

# (module relative to cmdb/, the expression the attribute is read from) -> why it may
ALLOWED_READS: dict[tuple[str, str], str] = {
    ('interface/rest_api/routes/user_management_routes/cmdb_groups/groups_routes.py', 'params'):
        "the group delete's MOVE target",
    ('interface/rest_api/responses/response_parameters/group_parameters.py', 'self'):
        'GroupDeletionParameters sets its MOVE target',
    ('interface/rest_api/responses/response_parameters/group_parameters.py', 'parameters'):
        'GroupDeletionParameters serialises its MOVE target',
    ('models/access_model/cmdb_access_assignment.py', 'self'):
        'an assignment grants one user group - it names a group, not a membership',
    ('models/access_model/cmdb_access_assignment.py', 'instance'):
        'an assignment serialises the one user group it grants',
}


def _reads() -> list[tuple[str, int, str]]:
    """Every ``<expression>.group_id`` in cmdb/ outside the migrations: (module, line, expression)"""
    found: list[tuple[str, int, str]] = []

    for module in sorted(CMDB_ROOT.rglob('*.py')):
        if MIGRATIONS_DIR in module.relative_to(CMDB_ROOT).parts:
            continue

        for node in ast.walk(ast.parse(module.read_text(encoding='utf-8'))):
            if isinstance(node, ast.Attribute) and node.attr == SINGLE_GROUP_ATTRIBUTE:
                found.append((module.relative_to(CMDB_ROOT).as_posix(), node.lineno, ast.unparse(node.value)))

    return found


def test_no_single_group_attribute_is_read() -> None:
    """Only the MOVE target - every other reader takes the user's whole group list"""
    assert [read for read in _reads() if (read[0], read[2]) not in ALLOWED_READS] == []


@pytest.mark.parametrize('allowed', sorted(ALLOWED_READS))
def test_every_allowed_read_still_exists(allowed: tuple[str, str]) -> None:
    """A stale entry fails, so the list shrinks with the code"""
    assert allowed in {(module, expression) for module, _line, expression in _reads()}
