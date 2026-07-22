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
Unit tests for cmdb.framework.exporter.writer.base_export_writer

`export()` and `from_database()` are exercised without a database: a fake export format captures what
it is handed, and ObjectsManager / RenderList / BuilderParameters are patched at the module path so the
fetch+render wiring can be asserted in isolation.
"""
import re
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from cmdb.framework.exporter.writer.base_export_writer import BaseExportWriter
# -------------------------------------------------------------------------------------------------------------------- #

MODULE_PATH: str = 'cmdb.framework.exporter.writer.base_export_writer'
FILENAME_PATTERN: str = r'^attachment; filename=\d{4}_\d{2}_\d{2}-\d{2}_\d{2}_\d{2}\.json$'


class _FakeFormat:
    """A minimal export format that records its export() args and returns fixed content."""
    FILE_EXTENSION = 'json'
    MIME_TYPE = 'application/json'

    def __init__(self) -> None:
        self.called_with = None

    def export(self, data, options):
        """Records (data, options) and returns fixed content."""
        self.called_with = (data, options)
        return 'EXPORTED_CONTENT'


class _FakeZipFormat(_FakeFormat):
    """A fake format declaring a different MIME_TYPE / extension (a binary format)."""
    FILE_EXTENSION = 'zip'
    MIME_TYPE = 'application/zip'


class TestExport:
    """export() wraps the format output in a timestamped download Response."""

    def test_builds_download_response(self) -> None:
        """The response carries the format content, its declared mimetype and a timestamped filename."""
        fmt = _FakeFormat()
        writer = BaseExportWriter(fmt, SimpleNamespace(options={'view': 'native'}))
        writer.data = ['row-1', 'row-2']

        response = writer.export()

        assert response.get_data(as_text=True) == 'EXPORTED_CONTENT'
        assert response.mimetype == 'application/json'
        assert re.match(FILENAME_PATTERN, response.headers['Content-Disposition'])
        # the format received the collected data + the config options
        assert fmt.called_with == (['row-1', 'row-2'], {'view': 'native'})

    def test_uses_the_formats_declared_mime_type(self) -> None:
        """The response mimetype is exactly the export format's declared MIME_TYPE."""
        writer = BaseExportWriter(_FakeZipFormat(), SimpleNamespace(options={}))
        writer.data = []

        assert writer.export().mimetype == 'application/zip'


class TestFromDatabase:
    """from_database() fetches objects under the ACL permission and renders them into self.data."""

    def test_fetches_filters_and_renders(self) -> None:
        """Objects are iterated with the configured filter/sort/order and rendered via RenderList."""
        dbm = MagicMock()
        user = MagicMock()
        permission = MagicMock()
        params = SimpleNamespace(filter={'type_id': 1}, sort='public_id', order=1)
        writer = BaseExportWriter(_FakeFormat(), SimpleNamespace(parameters=params, options={}))

        with patch(f'{MODULE_PATH}.ObjectsManager') as objects_manager_cls, \
             patch(f'{MODULE_PATH}.BuilderParameters') as builder_params_cls, \
             patch(f'{MODULE_PATH}.RenderList') as render_list_cls:
            objects_manager_cls.return_value.iterate.return_value = SimpleNamespace(results=['obj-1', 'obj-2'])
            render_list_cls.return_value.render_result_list.return_value = ['rendered']

            writer.from_database(dbm, user, permission, db_name='cloud_db')

        objects_manager_cls.assert_called_once_with(dbm, 'cloud_db')
        builder_params_cls.assert_called_once_with(criteria={'type_id': 1}, sort='public_id', order=1)
        objects_manager_cls.return_value.iterate.assert_called_once_with(
            builder_params_cls.return_value, user, permission
        )
        render_list_cls.assert_called_once_with(['obj-1', 'obj-2'], user, True)
        render_list_cls.return_value.render_result_list.assert_called_once_with(raw=False)
        assert writer.data == ['rendered']

    def test_default_db_name_is_none(self) -> None:
        """Without an explicit db_name the ObjectsManager is built against the default database (None)."""
        dbm = MagicMock()
        params = SimpleNamespace(filter={}, sort='public_id', order=1)
        writer = BaseExportWriter(_FakeFormat(), SimpleNamespace(parameters=params, options={}))

        with patch(f'{MODULE_PATH}.ObjectsManager') as objects_manager_cls, \
             patch(f'{MODULE_PATH}.BuilderParameters'), \
             patch(f'{MODULE_PATH}.RenderList') as render_list_cls:
            objects_manager_cls.return_value.iterate.return_value = SimpleNamespace(results=[])
            render_list_cls.return_value.render_result_list.return_value = []

            writer.from_database(dbm, MagicMock(), MagicMock())

        objects_manager_cls.assert_called_once_with(dbm, None)
