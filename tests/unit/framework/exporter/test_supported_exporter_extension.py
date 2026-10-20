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
Unit tests for cmdb.framework.exporter.writer.supported_exporter_extension
"""
from cmdb.framework.exporter.writer.supported_exporter_extension import SupportedExporterExtension
from cmdb.framework.exporter.exporter_constants import ExporterExtensionKey
# -------------------------------------------------------------------------------------------------------------------- #

EXPECTED_KEYS: set[str] = {key.value for key in ExporterExtensionKey}


class TestGetExtensions:
    """get_extensions returns the default format class names plus any custom ones."""

    def test_defaults(self) -> None:
        """The default catalogue is the four built-in format class names."""
        assert SupportedExporterExtension().get_extensions() == [
            'CsvExportFormat', 'JsonExportFormat', 'XlsxExportFormat', 'XmlExportFormat'
        ]

    def test_custom_extensions_are_appended(self) -> None:
        """Custom extensions are appended after the defaults."""
        extensions = SupportedExporterExtension(['ZipExportFormat']).get_extensions()
        assert extensions[-1] == 'ZipExportFormat'
        assert 'JsonExportFormat' in extensions


class TestConvertTo:
    """convert_to describes each format as a frontend-ready metadata dict."""

    def test_one_entry_per_extension_with_all_keys(self) -> None:
        """Every default format is described with exactly the ExporterExtensionKey fields."""
        catalogue = SupportedExporterExtension().convert_to()

        assert [entry[ExporterExtensionKey.EXTENSION.value] for entry in catalogue] == \
            SupportedExporterExtension().get_extensions()
        for entry in catalogue:
            assert set(entry) == EXPECTED_KEYS

    def test_metadata_reflects_the_format_class(self) -> None:
        """The metadata values are read from the format class attributes (spot-check CSV)."""
        catalogue = SupportedExporterExtension().convert_to()
        csv_entry = next(e for e in catalogue if e[ExporterExtensionKey.EXTENSION.value] == 'CsvExportFormat')

        assert csv_entry[ExporterExtensionKey.LABEL.value] == 'CSV'
        # CSV can only export a single type, so it does not support multi-type export
        assert csv_entry[ExporterExtensionKey.MULTI_TYPE_SUPPORT.value] is False

    def test_returns_fresh_copies_not_the_cached_objects(self) -> None:
        """Mutating a returned entry must not corrupt the cached catalogue used by later calls."""
        first = SupportedExporterExtension().convert_to()
        first[0][ExporterExtensionKey.LABEL.value] = 'MUTATED'

        second = SupportedExporterExtension().convert_to()
        assert second[0][ExporterExtensionKey.LABEL.value] != 'MUTATED'
