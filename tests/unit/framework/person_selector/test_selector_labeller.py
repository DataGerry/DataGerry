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
Unit tests for cmdb.framework.person_selector.selector_labeller - person selector values as the text a summary line
shows: one resolution for all values, each value its visible labels
"""
from typing import Any
from unittest.mock import MagicMock, patch

from cmdb.framework.person_selector import selector_labeller
from cmdb.framework.person_selector.selector_labeller import person_labeller
# -------------------------------------------------------------------------------------------------------------------- #

ADA: int = 11
BOB: int = 12
HIDDEN: int = 13
RESOLVE_PATH: str = f'{selector_labeller.__name__}.resolve_person_selections'
VISIBLE: dict[int, dict[str, Any]] = {
    ADA: {'object_id': ADA, 'label': 'Ada'},
    BOB: {'object_id': BOB, 'label': 'Bob'},
}


def test_every_value_is_resolved_in_one_pass_and_labelled_in_order() -> None:
    """All ids of all values go to one resolution; each value gets its own text, hidden ids left out"""
    objects_manager, types_manager, hidden = MagicMock(), MagicMock(), MagicMock()

    with patch(RESOLVE_PATH, return_value=VISIBLE) as resolve:
        texts: list[str] = person_labeller(objects_manager, types_manager, hidden)([[ADA, HIDDEN], BOB, [HIDDEN]])

    assert texts == ['Ada', 'Bob', '']
    resolve.assert_called_once_with(objects_manager, types_manager, hidden, {ADA, BOB, HIDDEN})


def test_building_the_labeller_reads_nothing() -> None:
    """The labeller resolves when called, never when built"""
    with patch(RESOLVE_PATH) as resolve:
        person_labeller(MagicMock(), MagicMock(), MagicMock())

    resolve.assert_not_called()


def test_values_without_ids_resolve_nothing_and_show_nothing() -> None:
    """Empty values ask the resolution for no id and answer the empty text"""
    with patch(RESOLVE_PATH, return_value={}) as resolve:
        texts: list[str] = person_labeller(MagicMock(), MagicMock(), MagicMock())([None, []])

    assert texts == ['', '']
    assert resolve.call_args.args[3] == set()
