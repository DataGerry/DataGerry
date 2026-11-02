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
Unit tests for cmdb.framework.special_type_marker

A held type of the asked id answers without a read; any other case reads the stored type, and a missing type has no
marker
"""
from unittest.mock import MagicMock

from cmdb.framework.special_type_marker import read_special_type_marker
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 7
OTHER_TYPE_ID: int = 8
HELD_MARKER: str = 'RACK'
STORED_MARKER: str = 'SUBNET'


def _held(type_id: int, marker: str | None) -> MagicMock:
    """A CmdbType the caller holds"""
    held = MagicMock()
    held.public_id = type_id
    held.special_type = marker

    return held


def _types_manager(stored: dict | None) -> MagicMock:
    """A TypesManager answering this type document"""
    manager = MagicMock()
    manager.get_type.return_value = stored

    return manager


def test_the_held_type_answers_without_a_read() -> None:
    """The update's cached type"""
    manager = _types_manager({'special_type': STORED_MARKER})

    assert read_special_type_marker(manager, TYPE_ID, _held(TYPE_ID, HELD_MARKER)) == HELD_MARKER
    manager.get_type.assert_not_called()


def test_a_held_type_without_a_marker_answers_none_without_a_read() -> None:
    """A plain type the caller holds"""
    manager = _types_manager({'special_type': STORED_MARKER})

    assert read_special_type_marker(manager, TYPE_ID, _held(TYPE_ID, None)) is None
    manager.get_type.assert_not_called()


def test_a_held_type_of_another_id_is_read_past() -> None:
    """Only the asked type is trusted"""
    manager = _types_manager({'special_type': STORED_MARKER})

    assert read_special_type_marker(manager, TYPE_ID, _held(OTHER_TYPE_ID, HELD_MARKER)) == STORED_MARKER
    manager.get_type.assert_called_once_with(TYPE_ID)


def test_without_a_held_type_the_stored_one_is_read() -> None:
    """The create and the imports"""
    assert read_special_type_marker(_types_manager({'special_type': STORED_MARKER}), TYPE_ID) == STORED_MARKER


def test_a_missing_type_has_no_marker() -> None:
    """No type document, no marker"""
    assert read_special_type_marker(_types_manager(None), TYPE_ID) is None
