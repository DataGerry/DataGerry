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
Integration tests for the characters an object export writes, against a real MongoDB and the real renderer

``BaseExportWriter.from_database`` reads and renders a stored object whose field value and MDS row value span lines
and hold a tab; the XML and the XLSX written from it read back exactly. A stored control character XML 1.0 cannot
carry is refused by both with ``ExporterCharacterError``, naming the object and the field
"""
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from io import BytesIO

import pytest
from openpyxl import load_workbook

from cmdb.database import MongoDatabaseManager
from cmdb.framework.exporter.config.exporter_config import ExporterConfig
from cmdb.framework.exporter.format.base_exporter_format import BaseExporterFormat
from cmdb.framework.exporter.format.xlsx_export_format import XlsxExportFormat
from cmdb.framework.exporter.format.xml_export_format import XmlExportFormat
from cmdb.framework.exporter.writer.base_export_writer import BaseExportWriter
from cmdb.interface.rest_api.responses.response_parameters.collection_parameters import CollectionParameters
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.errors.exporter import ExporterCharacterError
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 98401
OBJECT_ID: int = 98411
NOTE_FIELD: str = 'note'
SECTION_ID: str = 'lines'
ROW_FIELD: str = 'text'
NOTE_VALUE: str = 'first line\nsecond line\r\nthird\tcolumn'
ROW_VALUE: str = 'row line 1\nrow line 2\tend'


def _seed(database_manager: MongoDatabaseManager, database_name: str, note: str, row_value: str) -> None:
    """Writes the type and its one object"""
    _purge(database_manager, database_name)
    database_manager.get_collection(CmdbType.COLLECTION, database_name).insert_one(make_type_doc(
        TYPE_ID, 'export-characters-integration',
        fields=[{'type': 'text', 'name': NOTE_FIELD, 'label': 'Note'},
                {'type': 'text', 'name': ROW_FIELD, 'label': 'Text'}],
        sections=[{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [NOTE_FIELD]},
                  {'type': 'multi-data-section', 'name': SECTION_ID, 'label': 'Lines', 'fields': [ROW_FIELD]}],
    ))
    database_manager.get_collection(CmdbObject.COLLECTION, database_name).insert_one({
        'public_id': OBJECT_ID, 'type_id': TYPE_ID, 'active': True, 'author_id': 1, 'version': '1.0.0',
        'creation_time': datetime.now(timezone.utc), 'fields': [{'name': NOTE_FIELD, 'value': note}],
        'multi_data_sections': [{'section_id': SECTION_ID, 'highest_id': 1, 'values': [
            {'multi_data_id': 1, 'data': [{'name': ROW_FIELD, 'value': row_value}]},
        ]}],
    })


def _purge(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Removes the type and its objects"""
    database_manager.get_collection(CmdbType.COLLECTION, database_name).delete_many({'public_id': TYPE_ID})
    database_manager.get_collection(CmdbObject.COLLECTION, database_name).delete_many({'type_id': TYPE_ID})


@pytest.fixture(autouse=True)
def _context(rest_api, database_manager: MongoDatabaseManager, database_name: str):
    """Pushes the app context the renderer resolves its managers through; removes what a test seeded"""
    with rest_api.application.test_request_context():
        yield

    _purge(database_manager, database_name)


def _export(export_format: BaseExporterFormat, dbm: MongoDatabaseManager, user: CmdbUser) -> bytes:
    """The real export of the seeded object"""
    writer = BaseExportWriter(export_format, ExporterConfig(
        parameters=CollectionParameters(filter={'type_id': TYPE_ID}), options={}))
    writer.from_database(dbm, user, AccessControlPermission.READ)

    return writer.export().get_data()


class TestWhitespaceReadsBack:
    """What was stored is what a reader of the file gets."""

    def test_xml(self, database_manager, database_name, full_access_user: CmdbUser) -> None:
        """The field value and the MDS row value, line breaks and tabs included"""
        _seed(database_manager, database_name, NOTE_VALUE, ROW_VALUE)

        obj = ET.fromstring(_export(XmlExportFormat(), database_manager, full_access_user)).find('object')

        assert obj.find('fields/field').attrib['value'] == NOTE_VALUE
        assert obj.find('multi_data_sections/section/row/field').attrib['value'] == ROW_VALUE

    def test_xlsx(self, database_manager, database_name, full_access_user: CmdbUser) -> None:
        """The note cell and the MDS cell"""
        _seed(database_manager, database_name, NOTE_VALUE, ROW_VALUE)

        sheet = load_workbook(BytesIO(_export(XlsxExportFormat(), database_manager, full_access_user))).active
        values = [cell.value for cell in sheet[2]]

        assert NOTE_VALUE in values and ROW_VALUE in values


class TestAnUnwritableCharacter:
    """Refused by name, before any file is answered."""

    @pytest.mark.parametrize('export_format', [XmlExportFormat(), XlsxExportFormat()], ids=['xml', 'xlsx'])
    def test_in_a_field(self, database_manager, database_name, full_access_user: CmdbUser,
                        export_format: BaseExporterFormat) -> None:
        """The object and the field"""
        _seed(database_manager, database_name, 'bell\x07', ROW_VALUE)

        with pytest.raises(ExporterCharacterError, match=rf"Object {OBJECT_ID}, field '{NOTE_FIELD}'"):
            _export(export_format, database_manager, full_access_user)

    @pytest.mark.parametrize('export_format', [XmlExportFormat(), XlsxExportFormat()], ids=['xml', 'xlsx'])
    def test_in_an_mds_row(self, database_manager, database_name, full_access_user: CmdbUser,
                           export_format: BaseExporterFormat) -> None:
        """The object, the field and its section"""
        _seed(database_manager, database_name, NOTE_VALUE, 'esc\x1b')

        with pytest.raises(ExporterCharacterError,
                           match=rf"Object {OBJECT_ID}, field '{ROW_FIELD}' of multi-data section '{SECTION_ID}'"):
            _export(export_format, database_manager, full_access_user)
