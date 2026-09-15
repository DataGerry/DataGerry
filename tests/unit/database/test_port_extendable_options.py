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
Unit tests for the predefined Port Connectivity extendable options

Pure tests over the declared value lists: no Mongo, no Flask. They guard the two things a data file
like this can silently get wrong - a value duplicated inside its own list (which the database will
NOT catch, since CmdbExtendableOption declares only a non-unique index on option_type) and a document
built with the wrong shape or option_type.
"""
import pytest

from cmdb.database.predefined_data.port_data.port_extendable_options import (
    DEFAULT_CABLE_TYPE_VALUES,
    DEFAULT_PORT_SPEED_VALUES,
    DEFAULT_PORT_STATUS_VALUES,
    DEFAULT_PORT_TYPE_VALUES,
    PORT_OPTION_VALUES,
    get_default_port_extendable_options,
)
from cmdb.models.extendable_option_model import OptionType, ExtendableOptionKey
# -------------------------------------------------------------------------------------------------------------------- #

EXPECTED_COUNTS: dict[OptionType, int] = {
    OptionType.PORT_STATUS: 3,
    OptionType.PORT_TYPE: 13,
    OptionType.PORT_SPEED: 13,
    OptionType.CABLE_TYPE: 15,
}


class TestTheDeclaredLists:
    """The four value tuples themselves."""

    @pytest.mark.parametrize('values', [
        DEFAULT_PORT_STATUS_VALUES,
        DEFAULT_PORT_TYPE_VALUES,
        DEFAULT_PORT_SPEED_VALUES,
        DEFAULT_CABLE_TYPE_VALUES,
    ], ids=['status', 'type', 'speed', 'cable'])
    def test_no_list_repeats_a_value(self, values: tuple[str, ...]) -> None:
        """
        A duplicate inside one list would ship two identical dropdown entries.

        Worth its own test because nothing else catches it: the collection has a NON-unique index on
        option_type only, so MongoDB accepts duplicates happily.
        """
        assert len(values) == len(set(values))

    @pytest.mark.parametrize('values', [
        DEFAULT_PORT_STATUS_VALUES,
        DEFAULT_PORT_TYPE_VALUES,
        DEFAULT_PORT_SPEED_VALUES,
        DEFAULT_CABLE_TYPE_VALUES,
    ], ids=['status', 'type', 'speed', 'cable'])
    def test_every_value_is_a_non_blank_string(self, values: tuple[str, ...]) -> None:
        """An empty or whitespace-only option would render as an unselectable blank row."""
        assert all(isinstance(value, str) and value.strip() for value in values)

    def test_every_option_type_is_covered_exactly_once(self) -> None:
        """The pairing table names each of the feature's four lists, and no list twice."""
        covered = [option_type for option_type, _ in PORT_OPTION_VALUES]

        assert covered == [
            OptionType.PORT_STATUS, OptionType.PORT_TYPE, OptionType.PORT_SPEED, OptionType.CABLE_TYPE,
        ]

    def test_port_speeds_are_written_in_the_short_form(self) -> None:
        """
        The decided spelling: '1G', not '1 Gbps'.

        Pinned because it is a stored string that reaches customer databases and every export, so
        changing it later is a migration rather than an edit.
        """
        assert '1G' in DEFAULT_PORT_SPEED_VALUES
        assert not any('bps' in value for value in DEFAULT_PORT_SPEED_VALUES)

    def test_the_ambiguous_bare_qsfp_is_not_offered(self) -> None:
        """
        'QSFP' alone is not a form factor and would not distinguish 40G from 100G.

        The concept names it, so this test records that leaving it out is deliberate rather than an
        oversight - the specific cages are listed instead.
        """
        assert 'QSFP' not in DEFAULT_PORT_TYPE_VALUES
        assert {'QSFP+', 'QSFP28'} <= set(DEFAULT_PORT_TYPE_VALUES)


class TestTheBuiltDocuments:
    """get_default_port_extendable_options builds what the seeder and the updater insert."""

    def test_builds_one_document_per_declared_value(self) -> None:
        """Nothing is dropped or duplicated between the tuples and the documents."""
        declared = sum(len(values) for _, values in PORT_OPTION_VALUES)

        assert len(get_default_port_extendable_options()) == declared

    def test_every_document_carries_the_three_keys(self) -> None:
        """The shape CmdbExtendableOption expects, matching the ISMS seeder."""
        for option in get_default_port_extendable_options():
            assert set(option) == {
                ExtendableOptionKey.VALUE,
                ExtendableOptionKey.OPTION_TYPE,
                ExtendableOptionKey.PREDEFINED,
            }

    def test_every_document_is_marked_predefined(self) -> None:
        """Predefined is what distinguishes a shipped option from one a customer added."""
        assert all(option[ExtendableOptionKey.PREDEFINED] is True
                   for option in get_default_port_extendable_options())

    @pytest.mark.parametrize('option_type, expected', list(EXPECTED_COUNTS.items()), ids=str)
    def test_each_option_type_gets_its_values(self, option_type: OptionType, expected: int) -> None:
        """A per-list count, so a value lost from one tuple fails loudly rather than silently."""
        built = [option for option in get_default_port_extendable_options()
                 if option[ExtendableOptionKey.OPTION_TYPE] == option_type]

        assert len(built) == expected

    def test_no_document_is_a_duplicate_of_another(self) -> None:
        """
        The (option_type, value) identity is unique across the whole set.

        This is the property the updater's re-run safety relies on, so it is pinned at the source.
        """
        identities = [(option[ExtendableOptionKey.OPTION_TYPE], option[ExtendableOptionKey.VALUE])
                      for option in get_default_port_extendable_options()]

        assert len(identities) == len(set(identities))

    def test_a_fresh_list_is_returned_each_call(self) -> None:
        """
        The seeder mutates what it inserts (dbm.insert stamps a public_id into the dict).

        A cached module-level list would therefore come back carrying the previous run's ids.
        """
        first = get_default_port_extendable_options()
        first[0]['public_id'] = 1

        assert 'public_id' not in get_default_port_extendable_options()[0]
