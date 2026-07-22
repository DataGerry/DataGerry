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
Unit tests for cmdb.framework.exporter.format.xlsx_export_format
"""
import json
from io import BytesIO
from types import SimpleNamespace

from openpyxl import load_workbook

from cmdb.framework.exporter.format.xlsx_export_format import XlsxExportFormat, MAX_SHEET_TITLE_LENGTH
# -------------------------------------------------------------------------------------------------------------------- #


def _obj(object_id: int, type_id: int = 5, type_label: str = 'Server', fields=None) -> SimpleNamespace:
    """A stand-in RenderResult with the given fields (defaulting to one text field)."""
    return SimpleNamespace(
        fields=fields if fields is not None else [{'name': 'dg-name', 'type': 'text', 'value': 'host-1'}],
        object_information={'object_id': object_id, 'active': True},
        type_information={'type_id': type_id, 'type_label': type_label},
    )


def _workbook(data, *args):
    """Runs the XLSX export and loads the resulting bytes back into an openpyxl workbook."""
    return load_workbook(BytesIO(XlsxExportFormat().export(data, *args)))


class TestXlsxExport:
    """XlsxExportFormat.export serializes rendered objects into an XLSX workbook."""

    def test_native_export(self) -> None:
        """One worksheet named after the type, with the header row and one data row."""
        sheet = _workbook([_obj(10)])['Server']

        assert [sheet.cell(1, col).value for col in (1, 2, 3)] == ['public_id', 'active', 'dg-name']
        assert [sheet.cell(2, col).value for col in (1, 2, 3)] == ['10', 'True', 'host-1']

    def test_empty_export_yields_single_header_sheet(self) -> None:
        """An empty object list yields one valid, visible header-only worksheet (no IndexError / 500)."""
        workbook = _workbook([])

        assert len(workbook.sheetnames) == 1
        sheet = workbook.active
        assert [sheet.cell(1, col).value for col in (1, 2)] == ['public_id', 'active']
        assert sheet.cell(2, 1).value is None  # no data rows

    def test_multitype_export_uses_per_type_columns(self) -> None:
        """B2: each type's worksheet carries its own field columns, not the first type's."""
        server = _obj(10, type_id=5, type_label='Server',
                      fields=[{'name': 'dg-name', 'type': 'text', 'value': 'host-1'}])
        router = _obj(11, type_id=6, type_label='Router',
                      fields=[{'name': 'ip', 'type': 'text', 'value': '10.0.0.1'}])

        # Pass unsorted to also exercise the type_id sort
        workbook = _workbook([router, server])

        assert workbook.sheetnames == ['Server', 'Router']

        server_sheet = workbook['Server']
        assert [server_sheet.cell(1, col).value for col in (1, 2, 3)] == ['public_id', 'active', 'dg-name']
        assert [server_sheet.cell(2, col).value for col in (1, 2, 3)] == ['10', 'True', 'host-1']

        router_sheet = workbook['Router']
        assert [router_sheet.cell(1, col).value for col in (1, 2, 3)] == ['public_id', 'active', 'ip']
        assert [router_sheet.cell(2, col).value for col in (1, 2, 3)] == ['11', 'True', '10.0.0.1']

    def test_render_metadata_selects_header_and_columns(self) -> None:
        """A render-view metadata override fixes the header identity columns and the field columns."""
        metadata = json.dumps({'header': ['public_id'], 'columns': ['dg-name']})
        sheet = _workbook([_obj(10)], {'view': 'render', 'metadata': metadata})['Server']

        assert [sheet.cell(1, col).value for col in (1, 2)] == ['public_id', 'dg-name']
        assert sheet.cell(1, 3).value is None
        assert [sheet.cell(2, col).value for col in (1, 2)] == ['10', 'host-1']

    def test_declares_xlsx_mime_type(self) -> None:
        """XLSX declares the standard spreadsheet mime type (not the writer's text/<ext> fallback)."""
        assert XlsxExportFormat.MIME_TYPE == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


class TestNormalizeSheetTitle:
    """XlsxExportFormat._normalize_sheet_title sanitizes a type label for use as a sheet title."""
    # pylint: disable=protected-access

    def test_replaces_invalid_characters(self) -> None:
        """Excel-invalid characters are replaced with underscores."""
        assert XlsxExportFormat._normalize_sheet_title('a/b:c*d?e[f]g\\h') == 'a_b_c_d_e_f_g_h'

    def test_truncates_to_excel_limit(self) -> None:
        """A title longer than Excel's 31-character limit is truncated."""
        assert XlsxExportFormat._normalize_sheet_title('x' * 50) == 'x' * MAX_SHEET_TITLE_LENGTH
