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
Unit tests for cmdb.framework.importer.helper.importer_helper

DB-free: exercises the class registries and the three ``load_*`` resolvers. Focus: every
resolver rejects an unknown kind, an unknown file format, and a falsy registry entry with the
correct error class, that raw ``file_format`` strings resolve against the enum-keyed registries,
and that the registry keys stay in lock-step with the content-type ``FILE_TYPE`` contract.
"""
import pytest

from cmdb.framework.importer.helper import importer_helper
from cmdb.framework.importer.helper.importer_helper import (
    load_importer_class,
    load_importer_config_class,
    load_parser_class,
    OBJECT_IMPORTER_REGISTRY,
    OBJECT_IMPORTER_CONFIG_REGISTRY,
    OBJECT_PARSER_REGISTRY,
)
from cmdb.framework.importer.importer_constants import IMPORTER_KIND_OBJECT, ImporterFileFormat
from cmdb.framework.importer.content_types import JSONContent, CSVContent
from cmdb.framework.importer.importers.csv_object_importer import CsvObjectImporter
from cmdb.framework.importer.importers.json_object_importer import JsonObjectImporter
from cmdb.framework.importer.configs.csv_object_importer_config import CsvObjectImporterConfig
from cmdb.framework.importer.configs.json_object_importer_config import JsonObjectImporterConfig
from cmdb.framework.importer.parser.csv_object_parser import CsvObjectParser
from cmdb.framework.importer.parser.json_object_parser import JsonObjectParser

from cmdb.errors.importer import ImporterLoadError, ParserLoadError
# -------------------------------------------------------------------------------------------------------------------- #

UNKNOWN_KIND: str = 'not-a-kind'
UNKNOWN_FORMAT: str = 'yaml'


# -------------------------------------------------------------------------------------------------------------------- #
#                                            file-format / registry contract                                          #
# -------------------------------------------------------------------------------------------------------------------- #

class TestRegistryContract:
    """The registries are keyed by the file-format enum and stay aligned with FILE_TYPE."""

    def test_file_format_values_match_content_file_type(self) -> None:
        """The registry-key enum values are exactly the content-type FILE_TYPE identifiers."""
        assert ImporterFileFormat.JSON.value == JSONContent.FILE_TYPE
        assert ImporterFileFormat.CSV.value == CSVContent.FILE_TYPE

    def test_registries_share_the_same_format_keys(self) -> None:
        """Importer, config and parser registries all expose the JSON and CSV formats."""
        expected = {ImporterFileFormat.JSON, ImporterFileFormat.CSV}

        assert set(OBJECT_IMPORTER_REGISTRY) == expected
        assert set(OBJECT_IMPORTER_CONFIG_REGISTRY) == expected
        assert set(OBJECT_PARSER_REGISTRY) == expected

    def test_registries_map_to_the_expected_classes(self) -> None:
        """Each format resolves to its concrete importer / config / parser class."""
        assert OBJECT_IMPORTER_REGISTRY[ImporterFileFormat.JSON] is JsonObjectImporter
        assert OBJECT_IMPORTER_REGISTRY[ImporterFileFormat.CSV] is CsvObjectImporter
        assert OBJECT_IMPORTER_CONFIG_REGISTRY[ImporterFileFormat.JSON] is JsonObjectImporterConfig
        assert OBJECT_IMPORTER_CONFIG_REGISTRY[ImporterFileFormat.CSV] is CsvObjectImporterConfig
        assert OBJECT_PARSER_REGISTRY[ImporterFileFormat.JSON] is JsonObjectParser
        assert OBJECT_PARSER_REGISTRY[ImporterFileFormat.CSV] is CsvObjectParser

    def test_raw_string_format_resolves_against_enum_keys(self) -> None:
        """A plain 'csv' / 'json' string (as sent by a request) looks up the enum-keyed entry."""
        assert OBJECT_IMPORTER_REGISTRY['csv'] is CsvObjectImporter
        assert OBJECT_PARSER_REGISTRY['json'] is JsonObjectParser


# -------------------------------------------------------------------------------------------------------------------- #
#                                                load_importer_class                                                  #
# -------------------------------------------------------------------------------------------------------------------- #

class TestLoadImporterClass:
    """Resolving the concrete importer class."""

    @pytest.mark.parametrize('file_format, expected', [
        ('json', JsonObjectImporter),
        ('csv', CsvObjectImporter),
    ])
    def test_returns_the_class_for_a_known_format(self, file_format: str, expected: type) -> None:
        """A known kind + format returns the class itself (not an instance)."""
        assert load_importer_class(IMPORTER_KIND_OBJECT, file_format) is expected

    def test_unknown_kind_raises_importer_load_error(self) -> None:
        """An unknown import kind raises ImporterLoadError."""
        with pytest.raises(ImporterLoadError):
            load_importer_class(UNKNOWN_KIND, 'json')

    def test_unknown_format_raises_importer_load_error(self) -> None:
        """An unknown file format raises ImporterLoadError."""
        with pytest.raises(ImporterLoadError):
            load_importer_class(IMPORTER_KIND_OBJECT, UNKNOWN_FORMAT)


# -------------------------------------------------------------------------------------------------------------------- #
#                                             load_importer_config_class                                              #
# -------------------------------------------------------------------------------------------------------------------- #

class TestLoadImporterConfigClass:
    """Resolving the concrete importer-config class."""

    @pytest.mark.parametrize('file_format, expected', [
        ('json', JsonObjectImporterConfig),
        ('csv', CsvObjectImporterConfig),
    ])
    def test_returns_the_class_for_a_known_format(self, file_format: str, expected: type) -> None:
        """A known kind + format returns the config class itself."""
        assert load_importer_config_class(IMPORTER_KIND_OBJECT, file_format) is expected

    def test_unknown_kind_raises_importer_load_error(self) -> None:
        """An unknown kind raises ImporterLoadError, not a raw KeyError (B1 regression)."""
        with pytest.raises(ImporterLoadError):
            load_importer_config_class(UNKNOWN_KIND, 'json')

    def test_unknown_format_raises_importer_load_error(self) -> None:
        """An unknown file format raises ImporterLoadError."""
        with pytest.raises(ImporterLoadError):
            load_importer_config_class(IMPORTER_KIND_OBJECT, UNKNOWN_FORMAT)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 load_parser_class                                                   #
# -------------------------------------------------------------------------------------------------------------------- #

class TestLoadParserClass:
    """Resolving the concrete parser class."""

    @pytest.mark.parametrize('file_format, expected', [
        ('json', JsonObjectParser),
        ('csv', CsvObjectParser),
    ])
    def test_returns_the_class_for_a_known_format(self, file_format: str, expected: type) -> None:
        """A known kind + format returns the parser class itself."""
        assert load_parser_class(IMPORTER_KIND_OBJECT, file_format) is expected

    def test_unknown_kind_raises_parser_load_error(self) -> None:
        """An unknown parser kind raises ParserLoadError."""
        with pytest.raises(ParserLoadError):
            load_parser_class(UNKNOWN_KIND, 'json')

    def test_unknown_format_raises_parser_load_error(self) -> None:
        """An unknown file format raises ParserLoadError."""
        with pytest.raises(ParserLoadError):
            load_parser_class(IMPORTER_KIND_OBJECT, UNKNOWN_FORMAT)


# -------------------------------------------------------------------------------------------------------------------- #
#                                             falsy-entry guard (shared)                                              #
# -------------------------------------------------------------------------------------------------------------------- #

class TestFalsyRegistryEntry:
    """A registered-but-falsy entry is rejected with the resolver's error class."""

    def test_falsy_importer_entry_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A None importer entry raises ImporterLoadError."""
        monkeypatch.setitem(importer_helper.OBJECT_IMPORTER_REGISTRY, ImporterFileFormat.JSON, None)

        with pytest.raises(ImporterLoadError):
            load_importer_class(IMPORTER_KIND_OBJECT, 'json')

    def test_falsy_parser_entry_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A None parser entry raises ParserLoadError."""
        monkeypatch.setitem(importer_helper.OBJECT_PARSER_REGISTRY, ImporterFileFormat.JSON, None)

        with pytest.raises(ParserLoadError):
            load_parser_class(IMPORTER_KIND_OBJECT, 'json')
