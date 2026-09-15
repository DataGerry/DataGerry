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
Unit tests for cmdb.framework.exporter.config (ExporterConfig + ExporterConfigType)
"""
from unittest.mock import MagicMock

from cmdb.framework.exporter.config.exporter_config import ExporterConfig
from cmdb.framework.exporter.config.exporter_config_type_enum import ExporterConfigType
# -------------------------------------------------------------------------------------------------------------------- #


class TestExporterConfig:
    """ExporterConfig carries the collection parameters and the optional export params."""

    def test_stores_parameters_and_options(self) -> None:
        """Both parameters and options are stored as given."""
        params = MagicMock()
        options = {'classname': 'JsonExportFormat', 'zip': 'false'}
        config = ExporterConfig(params, options)

        assert config.parameters is params
        assert config.options == options

    def test_options_default_to_none(self) -> None:
        """options defaults to None when omitted."""
        assert ExporterConfig(MagicMock()).options is None

    def test_no_dead_config_type_attribute(self) -> None:
        """The dead `config_type` attribute has been removed."""
        assert not hasattr(ExporterConfig(MagicMock()), 'config_type')


class TestExporterConfigType:
    """ExporterConfigType is a string enum whose value matches the upper-cased `view` query param."""

    def test_values(self) -> None:
        """The members carry their own name as the string value."""
        assert ExporterConfigType.NATIVE.value == 'NATIVE'
        assert ExporterConfigType.RENDER.value == 'RENDER'

    def test_str_enum_equality(self) -> None:
        """As a BaseStrEnum, a member compares equal to its string value."""
        assert ExporterConfigType.RENDER == 'RENDER'

    def test_matches_upper_cased_view_param(self) -> None:
        """The render check performed by the format classes holds: 'render'.upper() == RENDER value."""
        assert 'render'.upper() == ExporterConfigType.RENDER.value
        assert 'native'.upper() != ExporterConfigType.RENDER.value
