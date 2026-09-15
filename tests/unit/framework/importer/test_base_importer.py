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
Unit tests for cmdb.framework.importer.importers.base_importer

DB-free: focus on the file/type/config accessors and that the abstract start_import raises.
"""
import pytest

from cmdb.framework.importer.importers.base_importer import BaseImporter
# -------------------------------------------------------------------------------------------------------------------- #


class TestBaseImporter:
    """The shared importer accessors."""

    def test_stores_file_and_type(self) -> None:
        """The file and file type are stored and exposed via the accessors."""
        importer = BaseImporter(file='/path/to/data.csv', file_type='csv')

        assert importer.get_file() == '/path/to/data.csv'
        assert importer.get_file_type() == 'csv'

    def test_has_config_false_without_config(self) -> None:
        """Without a config, has_config is False and get_config returns None."""
        importer = BaseImporter(file='x', file_type='csv')

        assert importer.has_config() is False
        assert importer.get_config() is None

    def test_has_config_true_with_config(self) -> None:
        """With a config, has_config is True and get_config returns it."""
        config = object()
        importer = BaseImporter(file='x', file_type='csv', config=config)

        assert importer.has_config() is True
        assert importer.get_config() is config

    def test_start_import_is_abstract(self) -> None:
        """The base start_import must be implemented by subclasses."""
        importer = BaseImporter(file='x', file_type='csv')

        with pytest.raises(NotImplementedError):
            importer.start_import()
