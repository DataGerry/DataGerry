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
Unit tests for the CmdbObject index declarations

Pins the compound (name, value) multikey indexes added for the $elemMatch{name, value}
query shape (IPAM reference lookups and field-value queries) alongside the pre-existing
value-only indexes, and confirms get_index_keys still materialises every declaration
"""
from cmdb.models.object_model.cmdb_object import CmdbObject
# -------------------------------------------------------------------------------------------------------------------- #


FIELDS_NAME_VALUE_INDEX: str = 'fields_name_value'
MDS_NAME_VALUE_INDEX: str = 'multi_data_sections_values_data_name_value'

FIELDS_NAME_PATH: str = 'fields.name'
FIELDS_VALUE_PATH: str = 'fields.value'
MDS_NAME_PATH: str = 'multi_data_sections.values.data.name'
MDS_VALUE_PATH: str = 'multi_data_sections.values.data.value'


def _index_by_name(name: str) -> dict:
    """Returns the INDEX_KEYS declaration with the given name (fails the test when absent)"""
    matches = [entry for entry in CmdbObject.INDEX_KEYS if entry.get('name') == name]

    assert len(matches) == 1, f"expected exactly one '{name}' index declaration"

    return matches[0]


def test_fields_compound_index_declares_name_then_value() -> None:
    """The fields compound index covers (fields.name, fields.value) in that order"""
    declaration = _index_by_name(FIELDS_NAME_VALUE_INDEX)

    assert [key for key, _ in declaration['keys']] == [FIELDS_NAME_PATH, FIELDS_VALUE_PATH]
    assert declaration['unique'] is False


def test_mds_compound_index_declares_name_then_value() -> None:
    """The MDS compound index covers (data.name, data.value) in that order"""
    declaration = _index_by_name(MDS_NAME_VALUE_INDEX)

    assert [key for key, _ in declaration['keys']] == [MDS_NAME_PATH, MDS_VALUE_PATH]
    assert declaration['unique'] is False


def test_value_only_indexes_are_retained() -> None:
    """The pre-existing value-only indexes stay declared for value-only query shapes"""
    assert _index_by_name('fields_value')['keys'] == [(FIELDS_VALUE_PATH, 1)]
    assert _index_by_name('multi_data_sections_values_data_value')['keys'] == [(MDS_VALUE_PATH, 1)]


def test_get_index_keys_materialises_every_declaration() -> None:
    """get_index_keys builds one IndexModel per INDEX_KEYS + SUPER_INDEX_KEYS entry"""
    models = CmdbObject.get_index_keys()

    assert len(models) == len(CmdbObject.INDEX_KEYS) + len(CmdbObject.SUPER_INDEX_KEYS)
