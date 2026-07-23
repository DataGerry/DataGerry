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
Unit tests for the import content-type identifiers (BaseContent / CSVContent / JSONContent)

DB-free contract lock: these class-level identifiers feed the FE-facing importer/parser metadata
(icon, content type, file type) and the parser registry keys, so their values are pinned here to
catch accidental edits.
"""
from cmdb.framework.importer.content_types.base_content import BaseContent
from cmdb.framework.importer.content_types.csv_content import CSVContent
from cmdb.framework.importer.content_types.json_content import JSONContent
# -------------------------------------------------------------------------------------------------------------------- #


class TestBaseContent:
    """The base content type carries empty identifiers."""

    def test_defaults_are_empty(self) -> None:
        """BaseContent exposes empty icon/content-type/file-type slots."""
        assert BaseContent.ICON == ''
        assert BaseContent.CONTENT_TYPE == ''
        assert BaseContent.FILE_TYPE == ''


class TestCsvContent:
    """The CSV content-type identifiers."""

    def test_identifiers(self) -> None:
        """CSVContent pins the CSV icon, MIME type and file type."""
        assert CSVContent.ICON == 'fas fa-file-csv'
        assert CSVContent.CONTENT_TYPE == 'text/csv'
        assert CSVContent.FILE_TYPE == 'csv'

    def test_is_base_content(self) -> None:
        """CSVContent extends BaseContent."""
        assert issubclass(CSVContent, BaseContent)


class TestJsonContent:
    """The JSON content-type identifiers."""

    def test_identifiers(self) -> None:
        """JSONContent pins the JSON icon, MIME type and file type."""
        assert JSONContent.ICON == 'fas fa-file-code'
        assert JSONContent.CONTENT_TYPE == 'application/json'
        assert JSONContent.FILE_TYPE == 'json'

    def test_is_base_content(self) -> None:
        """JSONContent extends BaseContent."""
        assert issubclass(JSONContent, BaseContent)
