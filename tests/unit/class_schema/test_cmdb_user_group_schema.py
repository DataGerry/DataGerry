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
Unit tests for the ``rights`` item rule of cmdb.class_schema.group_model.cmdb_user_group_schema

Pure Cerberus tests: every entry is a string. That a name exists in the right tree is the write routes' check
(``groups_helper.abort_if_unknown_rights``), not the schema's
"""
from typing import Any

import pytest
from cerberus import Validator

from cmdb.class_schema.write_schema_helper import build_write_schema
from cmdb.models.group_model import CmdbUserGroup, MASTER_RIGHT_NAME
# -------------------------------------------------------------------------------------------------------------------- #

KNOWN_RIGHT: str = 'base.framework.object.view'


def _validates(rights: Any) -> bool:
    """Whether the group write schema accepts the rights value."""
    return Validator(build_write_schema(CmdbUserGroup.SCHEMA), purge_unknown=True).validate(
        {'name': 'a-group', 'rights': rights})


@pytest.mark.parametrize('rights', [[], [KNOWN_RIGHT], [KNOWN_RIGHT, MASTER_RIGHT_NAME]],
                         ids=['empty', 'one', 'several'])
def test_string_entries_are_accepted(rights: list[str]) -> None:
    """An empty list is a group without rights"""
    assert _validates(rights)


@pytest.mark.parametrize('entry', [{}, 1, None, True, [KNOWN_RIGHT], {'name': KNOWN_RIGHT}],
                         ids=['empty-document', 'number', 'null', 'boolean', 'nested-list', 'right-document'])
def test_an_entry_that_is_no_string_is_refused(entry: Any) -> None:
    """The empty document is the one that made a stored group unreadable"""
    assert not _validates([KNOWN_RIGHT, entry])


def test_a_bare_string_is_refused() -> None:
    """A bare string would be read character by character"""
    assert not _validates(KNOWN_RIGHT)


def test_null_rights_are_normalised_to_an_empty_list() -> None:
    """Cerberus applies the default to a null as well as to an absent key, so null means no rights"""
    validator = Validator(build_write_schema(CmdbUserGroup.SCHEMA), purge_unknown=True)

    assert validator.validate({'name': 'a-group', 'rights': None})
    assert validator.document['rights'] == []
