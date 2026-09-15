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
Unit tests for the import mapper primitives (MapEntry / Mapping)

DB-free: accessors + option subset-matching on MapEntry, and the Mapping collection contract
(iteration, length, entry access, option-filtered queries, and building a Mapping from a list).
"""
from cmdb.framework.importer.mapper.map_entry import MapEntry
from cmdb.framework.importer.mapper.mapping import Mapping
# -------------------------------------------------------------------------------------------------------------------- #


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     MapEntry                                                        #
# -------------------------------------------------------------------------------------------------------------------- #

class TestMapEntry:
    """A single mapping entry: name, value and options."""

    def test_accessors(self) -> None:
        """get_name / get_value / get_options return the constructor values."""
        entry = MapEntry('active', 'col_active', type='property', ref_name='x')

        assert entry.get_name() == 'active'
        assert entry.get_value() == 'col_active'
        assert entry.get_options() == {'type': 'property', 'ref_name': 'x'}

    def test_options_default_to_empty(self) -> None:
        """With no options the entry exposes an empty options dict."""
        entry = MapEntry('n', 'v')

        assert not entry.get_options()

    def test_has_option_true_for_matching_subset(self) -> None:
        """has_option is True when the query is a subset of the entry's options."""
        entry = MapEntry('n', 'v', type='field', ref_name='x')

        assert entry.has_option({'type': 'field'}) is True

    def test_has_option_false_for_non_matching(self) -> None:
        """has_option is False when the query is not a subset of the options."""
        entry = MapEntry('n', 'v', type='field')

        assert entry.has_option({'type': 'ref'}) is False


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     Mapping                                                         #
# -------------------------------------------------------------------------------------------------------------------- #

class TestMapping:
    """The mapping collection."""

    def test_empty_by_default(self) -> None:
        """A new mapping has no entries."""
        mapping = Mapping()

        assert len(mapping) == 0
        assert mapping.get_entries() == []

    def test_initialised_with_entries(self) -> None:
        """A mapping constructed with entries exposes them and its length."""
        entries = [MapEntry('a', '0'), MapEntry('b', '1')]
        mapping = Mapping(entries)

        assert len(mapping) == 2
        assert mapping.get_entries() == entries

    def test_is_iterable(self) -> None:
        """Iterating the mapping yields its entries in order."""
        entries = [MapEntry('a', '0'), MapEntry('b', '1')]
        mapping = Mapping(entries)

        assert list(mapping) == entries

    def test_add_entry(self) -> None:
        """add_entry appends to the mapping."""
        mapping = Mapping()
        entry = MapEntry('a', '0')

        mapping.add_entry(entry)

        assert mapping.get_entries() == [entry]

    def test_get_entries_with_option_filters_by_subset(self) -> None:
        """get_entries_with_option returns only entries whose options match the query."""
        prop = MapEntry('active', 'c0', type='property')
        field = MapEntry('label', 'c1', type='field')
        ref = MapEntry('owner', 'c2', type='ref')
        mapping = Mapping([prop, field, ref])

        assert mapping.get_entries_with_option({'type': 'field'}) == [field]
        assert mapping.get_entries_with_option({'type': 'property'}) == [prop]
        assert mapping.get_entries_with_option({'type': 'missing'}) == []

    def test_generate_mapping_from_list(self) -> None:
        """generate_mapping_from_list builds a Mapping of MapEntry objects from dicts."""
        mapping = Mapping.generate_mapping_from_list([
            {'name': 'active', 'value': 'c0', 'type': 'property'},
            {'name': 'label', 'value': 'c1', 'type': 'field'},
        ])

        assert isinstance(mapping, Mapping)
        assert len(mapping) == 2
        first = mapping.get_entries()[0]
        assert isinstance(first, MapEntry)
        assert first.get_name() == 'active'
        assert first.get_options() == {'type': 'property'}

    def test_generate_mapping_from_empty_list(self) -> None:
        """An empty list yields an empty mapping."""
        assert len(Mapping.generate_mapping_from_list([])) == 0
