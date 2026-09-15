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
Unit tests for the concrete importer configs (JsonObjectImporterConfig / CsvObjectImporterConfig)

DB-free: verify the per-format metadata (MANUALLY_MAPPING + content-type identifiers) and that both
configs use the inherited ObjectImporterConfig constructor — JSON returns its fixed dict default
mapping (manual mapping off), CSV builds a Mapping from a supplied list (manual mapping on).
"""
from cmdb.framework.importer.configs.json_object_importer_config import JsonObjectImporterConfig
from cmdb.framework.importer.configs.csv_object_importer_config import CsvObjectImporterConfig
from cmdb.framework.importer.configs.object_importer_config import ObjectImporterConfig
from cmdb.framework.importer.mapper.mapping import Mapping
# -------------------------------------------------------------------------------------------------------------------- #


# -------------------------------------------------------------------------------------------------------------------- #
#                                            JsonObjectImporterConfig                                                #
# -------------------------------------------------------------------------------------------------------------------- #

class TestJsonObjectImporterConfig:
    """The JSON importer config uses a fixed dict mapping and disables manual mapping."""

    def test_metadata(self) -> None:
        """Manual mapping is off and the JSON content-type identifiers are exposed."""
        config = JsonObjectImporterConfig(type_id=1)

        assert isinstance(config, ObjectImporterConfig)
        assert config.MANUALLY_MAPPING is False
        assert config.FILE_TYPE == 'json'
        assert config.CONTENT_TYPE == 'application/json'

    def test_default_mapping_is_the_fixed_dict(self) -> None:
        """With no mapping supplied the config returns its fixed dict DEFAULT_MAPPING."""
        config = JsonObjectImporterConfig(type_id=2)

        assert config.get_mapping() == {
            'properties': {'public_id': 'public_id', 'active': 'active'},
            'fields': {},
        }

    def test_stores_type_id_and_bounds(self) -> None:
        """The inherited constructor stores type_id and the processing bounds."""
        config = JsonObjectImporterConfig(type_id=9, start_element=1, max_elements=5, overwrite_public=False)

        assert config.get_type_id() == 9
        assert config.start_element == 1
        assert config.max_elements == 5
        assert config.overwrite_public is False


# -------------------------------------------------------------------------------------------------------------------- #
#                                             CsvObjectImporterConfig                                                #
# -------------------------------------------------------------------------------------------------------------------- #

class TestCsvObjectImporterConfig:
    """The CSV importer config requires a manual mapping."""

    def test_metadata(self) -> None:
        """Manual mapping is on and the CSV content-type identifiers are exposed."""
        config = CsvObjectImporterConfig(type_id=1)

        assert isinstance(config, ObjectImporterConfig)
        assert config.MANUALLY_MAPPING is True
        assert config.FILE_TYPE == 'csv'
        assert config.CONTENT_TYPE == 'text/csv'

    def test_mapping_list_builds_a_mapping(self) -> None:
        """A supplied mapping list is turned into a Mapping via the inherited constructor."""
        config = CsvObjectImporterConfig(type_id=1, mapping=[{'name': 'a', 'value': '0'}])

        assert isinstance(config.get_mapping(), Mapping)
        assert len(config.get_mapping()) == 1

    def test_no_mapping_gets_a_fresh_empty_mapping(self) -> None:
        """Without a mapping the config gets a fresh empty Mapping (not a dict default)."""
        config = CsvObjectImporterConfig(type_id=1)

        assert isinstance(config.get_mapping(), Mapping)
        assert len(config.get_mapping()) == 0

    def test_stores_type_id_and_bounds(self) -> None:
        """The inherited constructor stores type_id and the processing bounds."""
        config = CsvObjectImporterConfig(type_id=4, start_element=2, max_elements=8, overwrite_public=False)

        assert config.get_type_id() == 4
        assert config.start_element == 2
        assert config.max_elements == 8
        assert config.overwrite_public is False
