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
Unit tests for cmdb.framework.port.port_text_rules

Pure tests. Pins the one text cap of the port surface - TEXT_VALUE_MAX_LENGTH, the type text cap - on
the values no request schema sees: the preview's inputs, the bulk descriptions and every generated name
"""
from typing import Any

import pytest

from cmdb.framework.port.port_text_constants import NAME_EXCERPT_LENGTH, PortTextError
from cmdb.framework.port.port_text_rules import long_name_blockers, text_value_blockers
from cmdb.models.type_model.type_constants import TEXT_VALUE_MAX_LENGTH
# -------------------------------------------------------------------------------------------------------------------- #

FIELD: str = 'prefix'
OTHER_FIELD: str = 'slot'


class TestTextValueBlockers:
    """The named values must be text within the cap."""

    def test_a_value_at_the_cap_passes(self) -> None:
        """255 characters is allowed"""
        assert text_value_blockers({FIELD: 'x' * TEXT_VALUE_MAX_LENGTH}, [FIELD]) == []

    def test_a_value_over_the_cap_is_refused_with_its_length(self) -> None:
        """One more is not - the message names the field, its length and the cap"""
        assert text_value_blockers({FIELD: 'x' * (TEXT_VALUE_MAX_LENGTH + 1)}, [FIELD]) == [
            PortTextError.TOO_LONG.format(field=FIELD, length=TEXT_VALUE_MAX_LENGTH + 1,
                                          maximum=TEXT_VALUE_MAX_LENGTH),
        ]

    @pytest.mark.parametrize('value, value_type', [(7, 'int'), ({'a': 1}, 'dict'), (['x'], 'list'), (True, 'bool')],
                             ids=['int', 'dict', 'list', 'bool'])
    def test_a_value_that_is_not_text_is_refused(self, value: Any, value_type: str) -> None:
        """Never coerced into one"""
        assert text_value_blockers({FIELD: value}, [FIELD]) == [
            PortTextError.NOT_TEXT.format(field=FIELD, value_type=value_type),
        ]

    @pytest.mark.parametrize('values', [{}, {FIELD: None}], ids=['absent', 'null'])
    def test_an_absent_or_null_value_is_not_judged(self, values: dict[str, Any]) -> None:
        """Every one of these values is optional"""
        assert text_value_blockers(values, [FIELD]) == []

    def test_every_reason_is_reported_in_key_order(self) -> None:
        """A caller fixes one request, not one field per submission"""
        blockers = text_value_blockers({FIELD: 1, OTHER_FIELD: 'x' * (TEXT_VALUE_MAX_LENGTH + 1)},
                                       [OTHER_FIELD, FIELD])

        assert [f"'{OTHER_FIELD}'" in blockers[0], f"'{FIELD}'" in blockers[1]] == [True, True]

    def test_a_key_not_named_is_not_judged(self) -> None:
        """Only the named keys"""
        assert text_value_blockers({OTHER_FIELD: 1}, [FIELD]) == []


class TestLongNameBlockers:
    """Generated names must fit a port name."""

    def test_names_at_the_cap_pass(self) -> None:
        """255 characters is a valid name"""
        assert long_name_blockers(['n' * TEXT_VALUE_MAX_LENGTH, 'short']) == []

    def test_no_names_pass(self) -> None:
        """An empty batch is nothing to refuse"""
        assert long_name_blockers([]) == []

    def test_one_reason_for_the_whole_batch(self) -> None:
        """A thousand too-long names are one message counting them and quoting the first"""
        first: str = 'a' * (TEXT_VALUE_MAX_LENGTH + 3)
        blockers = long_name_blockers([first, 'ok', 'b' * (TEXT_VALUE_MAX_LENGTH + 1)])

        assert blockers == [PortTextError.NAMES_TOO_LONG.format(
            count=2, maximum=TEXT_VALUE_MAX_LENGTH, excerpt='a' * NAME_EXCERPT_LENGTH + '...',
            length=TEXT_VALUE_MAX_LENGTH + 3,
        )]

    def test_the_quoted_name_is_cut(self) -> None:
        """Never the whole name - enough to recognise it"""
        blockers = long_name_blockers(['c' * (TEXT_VALUE_MAX_LENGTH + 1)])

        assert 'c' * (NAME_EXCERPT_LENGTH + 1) not in blockers[0]
