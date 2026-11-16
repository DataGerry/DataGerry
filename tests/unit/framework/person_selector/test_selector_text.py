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
Unit tests for cmdb.framework.person_selector.selector_text - selections as text, values cut to the visible ids
"""
from typing import Any

import pytest

from cmdb.framework.person_selector.selector_text import (
    kept_value,
    selection_labels_text,
    visible_labels_text,
    visible_selections,
)
# -------------------------------------------------------------------------------------------------------------------- #

ADA: int = 11
BOB: int = 12
HIDDEN: int = 13
UNLABELLED: int = 14

VISIBLE: dict[int, dict[str, Any]] = {
    ADA: {'object_id': ADA, 'label': 'Ada'},
    BOB: {'object_id': BOB, 'label': 'Bob'},
    UNLABELLED: {'object_id': UNLABELLED, 'label': None},
}


@pytest.mark.parametrize('value, multiple, expected', [
    ([BOB, HIDDEN, ADA], True, [BOB, ADA]),
    ([HIDDEN], True, []),
    (None, True, []),
    (ADA, False, ADA),
    (HIDDEN, False, None),
    (None, False, None),
], ids=['several-keeps-order', 'several-all-hidden', 'several-empty', 'one-visible', 'one-hidden', 'one-empty'])
def test_kept_value_keeps_the_visible_ids_in_the_selectors_shape(value: Any, multiple: bool, expected: Any) -> None:
    """A list for a selector holding several, one id or None otherwise"""
    assert kept_value(value, multiple, VISIBLE) == expected


def test_visible_selections_follow_the_values_order() -> None:
    """Hidden ids are left out"""
    assert visible_selections([BOB, HIDDEN, ADA], VISIBLE) == [VISIBLE[BOB], VISIBLE[ADA]]


@pytest.mark.parametrize('selections, expected', [
    ([VISIBLE[ADA], VISIBLE[BOB]], 'Ada, Bob'),
    ([VISIBLE[UNLABELLED]], str(UNLABELLED)),
    ([], ''),
], ids=['labels-joined', 'id-without-label', 'none'])
def test_selection_labels_text(selections: list[dict[str, Any]], expected: str) -> None:
    """A selection without a label shows its id"""
    assert selection_labels_text(selections) == expected


@pytest.mark.parametrize('value, expected', [
    ([ADA, HIDDEN, BOB], 'Ada, Bob'),
    (HIDDEN, ''),
    (None, ''),
    (BOB, 'Bob'),
], ids=['several', 'hidden-only', 'empty', 'one'])
def test_visible_labels_text_names_only_what_the_reader_may_see(value: Any, expected: str) -> None:
    """The text of a value"""
    assert visible_labels_text(value, VISIBLE) == expected
