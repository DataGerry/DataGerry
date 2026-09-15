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
Unit tests for the parser base classes (BaseParser / BaseObjectParser)

DB-free: focus on the config-merge contract (DEFAULT_CONFIG overlaid with caller values, omitted
keys keep their defaults, None means defaults-only) and that the abstract ``parse`` raises
NotImplementedError on both base classes.
"""
import pytest

from cmdb.framework.importer.parser.base_parser import BaseParser
from cmdb.framework.importer.parser.base_object_parser import BaseObjectParser
# -------------------------------------------------------------------------------------------------------------------- #


class _ConfiguredParser(BaseParser):  # pylint: disable=abstract-method
    """A BaseParser subclass with a non-empty DEFAULT_CONFIG for merge tests (parse unused)."""
    DEFAULT_CONFIG: dict = {'delimiter': ',', 'header': True}


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 config handling                                                     #
# -------------------------------------------------------------------------------------------------------------------- #

class TestConfigMerge:
    """The effective config is DEFAULT_CONFIG overlaid with the caller-supplied values."""

    def test_no_config_uses_defaults_only(self) -> None:
        """Omitting the config yields exactly DEFAULT_CONFIG."""
        assert _ConfiguredParser().get_config() == {'delimiter': ',', 'header': True}

    def test_none_config_uses_defaults_only(self) -> None:
        """Passing None is equivalent to passing nothing."""
        assert _ConfiguredParser(None).get_config() == {'delimiter': ',', 'header': True}

    def test_caller_values_override_defaults(self) -> None:
        """Supplied keys override defaults; omitted keys keep their default value."""
        config = _ConfiguredParser({'header': False}).get_config()

        assert config == {'delimiter': ',', 'header': False}

    def test_extra_keys_are_kept(self) -> None:
        """Keys not present in DEFAULT_CONFIG are added to the effective config."""
        config = _ConfiguredParser({'encoding': 'UTF-8'}).get_config()

        assert config == {'delimiter': ',', 'header': True, 'encoding': 'UTF-8'}

    def test_empty_default_config_returns_empty(self) -> None:
        """A base parser with the empty default and no input yields an empty config."""
        assert BaseParser().get_config() == {}

    def test_config_does_not_mutate_default_config(self) -> None:
        """Merging must not mutate the shared class-level DEFAULT_CONFIG."""
        _ConfiguredParser({'header': False, 'new': 1})

        assert _ConfiguredParser.DEFAULT_CONFIG == {'delimiter': ',', 'header': True}


# -------------------------------------------------------------------------------------------------------------------- #
#                                              abstract parse contract                                                #
# -------------------------------------------------------------------------------------------------------------------- #

class TestAbstractParse:
    """The base ``parse`` implementations are abstract."""

    def test_base_parser_parse_raises(self) -> None:
        """BaseParser.parse must be overridden by subclasses."""
        with pytest.raises(NotImplementedError):
            BaseParser().parse('some/file.csv')

    def test_base_object_parser_parse_raises(self) -> None:
        """BaseObjectParser.parse must be overridden by subclasses."""
        with pytest.raises(NotImplementedError):
            BaseObjectParser().parse('some/file.json')

    def test_base_object_parser_accepts_optional_config(self) -> None:
        """BaseObjectParser inherits BaseParser's optional-config constructor (no required arg)."""
        assert BaseObjectParser().get_config() == {}
