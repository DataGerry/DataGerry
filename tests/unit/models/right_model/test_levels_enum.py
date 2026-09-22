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
Unit tests for cmdb.models.right_model.levels_enum

Pure: no Mongo, no Flask. `Levels.as_name_map` is the catalogue `GET /rest/rights/levels` serves, so
these tests are about a WIRE format: which names appear, which numbers they carry and in which order.
The mapping used to be a hand-written dict in the constants module, and the tests that kept it in
step with the enum are what these replace - a derivation cannot drift, but it can still be reordered
or reshaped by a change to the enum itself.

The ordering is load-bearing twice over: `BaseRight`'s MIN_LEVEL / MAX_LEVEL bounds compare members
(pinned in `test_base_right.py`), and the JSON object preserves insertion order for the catalogue.
"""
from cmdb.models.right_model.levels_enum import Levels
# -------------------------------------------------------------------------------------------------------------------- #

# The catalogue as it goes over the wire: every name, its number, in the order the response carries
EXPECTED_CATALOGUE: dict[str, int] = {
    'CRITICAL': 100,
    'DANGER': 80,
    'SECURE': 50,
    'PROTECTED': 30,
    'PERMISSION': 10,
    'NOTSET': 0,
}


class TestAsNameMap:
    """Tests for the name -> level catalogue the levels route serves"""

    def test_is_the_published_catalogue(self) -> None:
        """Name, number and ORDER together - the response is a JSON object built from this dict."""
        assert list(Levels.as_name_map().items()) == [
            (name, Levels[name]) for name in EXPECTED_CATALOGUE
        ]

    def test_each_name_carries_its_own_number(self) -> None:
        """A member renumbered without its consumers is the failure this catches."""
        assert {name: int(level) for name, level in Levels.as_name_map().items()} == EXPECTED_CATALOGUE

    def test_covers_every_member_exactly_once(self) -> None:
        """A level added to the enum reaches the catalogue by construction - and nothing else does."""
        assert set(Levels.as_name_map()) == {level.name for level in Levels}
        assert len(Levels.as_name_map()) == len(Levels)

    def test_each_call_builds_a_fresh_mapping(self) -> None:
        """
        The catalogue is handed to the response, so it must not be shared state

        The module-level dict it replaced was passed to `GetSingleResponse` by reference: anything
        mutating what it got would have changed the catalogue for the rest of the process.
        """
        first = Levels.as_name_map()
        first.pop('CRITICAL')

        assert 'CRITICAL' in Levels.as_name_map()
