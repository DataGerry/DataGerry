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
Unit tests for the importer configuration base classes (BaseImporterConfig / ObjectImporterConfig)

DB-free: focus on mapping resolution — a caller list builds a fresh Mapping, an empty config gets a
fresh (non-shared) empty Mapping, a subclass dict DEFAULT_MAPPING is returned as-is — and on the
ObjectImporterConfig field storage / fail-fast on unknown kwargs.
"""
import pytest

from cmdb.framework.importer.configs.base_importer_config import BaseImporterConfig
from cmdb.framework.importer.configs.object_importer_config import ObjectImporterConfig
from cmdb.framework.importer.mapper.mapping import Mapping
# -------------------------------------------------------------------------------------------------------------------- #


# -------------------------------------------------------------------------------------------------------------------- #
#                                                BaseImporterConfig                                                   #
# -------------------------------------------------------------------------------------------------------------------- #

class TestBaseImporterConfig:
    """Mapping resolution in the base configuration."""

    def test_mapping_list_builds_a_mapping(self) -> None:
        """A caller-supplied list is turned into a Mapping with the given entries."""
        config = BaseImporterConfig(mapping=[{'name': 'a', 'value': '0'}, {'name': 'b', 'value': '1'}])

        assert isinstance(config.get_mapping(), Mapping)
        assert len(config.get_mapping()) == 2

    def test_empty_config_gets_a_fresh_empty_mapping(self) -> None:
        """Without a mapping the config gets an empty Mapping."""
        config = BaseImporterConfig()

        assert isinstance(config.get_mapping(), Mapping)
        assert len(config.get_mapping()) == 0

    def test_empty_configs_do_not_share_a_mapping_instance(self) -> None:
        """Two default configs must not alias the same mutable Mapping (B1)."""
        first = BaseImporterConfig()
        second = BaseImporterConfig()

        assert first.get_mapping() is not second.get_mapping()

    def test_dict_default_mapping_is_returned_as_is(self) -> None:
        """A subclass overriding DEFAULT_MAPPING with a dict gets that dict back (D2)."""
        class _DictDefaultConfig(BaseImporterConfig):
            DEFAULT_MAPPING = {'properties': {}, 'fields': {}}

        config = _DictDefaultConfig()

        assert config.get_mapping() == {'properties': {}, 'fields': {}}


# -------------------------------------------------------------------------------------------------------------------- #
#                                               ObjectImporterConfig                                                  #
# -------------------------------------------------------------------------------------------------------------------- #

class TestObjectImporterConfig:
    """The object import configuration adds type_id and processing bounds."""

    def test_stores_fields_and_defaults(self) -> None:
        """type_id is stored; the processing bounds fall back to their defaults."""
        config = ObjectImporterConfig(type_id=7)

        assert config.get_type_id() == 7
        assert config.start_element == 0
        assert config.max_elements == 0
        assert config.overwrite_public is True

    def test_custom_values(self) -> None:
        """Explicit processing bounds are stored as given."""
        config = ObjectImporterConfig(type_id=1, start_element=5, max_elements=10, overwrite_public=False)

        assert config.start_element == 5
        assert config.max_elements == 10
        assert config.overwrite_public is False

    def test_mapping_is_forwarded_to_base(self) -> None:
        """A mapping list still produces a Mapping via the base constructor."""
        config = ObjectImporterConfig(type_id=1, mapping=[{'name': 'x', 'value': '0'}])

        assert isinstance(config.get_mapping(), Mapping)
        assert len(config.get_mapping()) == 1

    def test_unknown_keyword_argument_is_rejected(self) -> None:
        """Unknown kwargs fail fast at this class (S1 — no *args/**kwargs passthrough)."""
        with pytest.raises(TypeError):
            ObjectImporterConfig(type_id=1, unexpected='value')  # pylint: disable=unexpected-keyword-arg
