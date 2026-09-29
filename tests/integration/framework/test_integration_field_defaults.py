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
Integration tests for field defaults against real stored types

The defaults the create fill uses are read off a CmdbType as the TypesManager returns it, and a type
stored before the default rule - one of its defaults breaking its own regex - is the case both fills
(the REST create's and the importer's) have to skip rather than fill
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import TypesManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.framework.importer.helper.object_import_validator import build_import_type_context
from cmdb.framework.object_field_defaults import fill_object_defaults
from cmdb.framework.object_field_value_rules import find_default_value_errors
from cmdb.models.type_model import CmdbType, SectionType
from cmdb.models.user_model import CmdbUser
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 9681
NOTE_FIELD: str = 'idf-note'
CODE_FIELD: str = 'idf-code'
ROW_FIELD: str = 'idf-row'
MDS_SECTION: str = 'idf-rows'
NOTE_DEFAULT: str = 'no note'
ROW_DEFAULT: str = 'eth'
LEGACY_CODE_DEFAULT: str = 'abc'   # breaks the field's own '[A-Z]+'

ADMIN: CmdbUser = CmdbUser(public_id=1, user_name='admin', active=True, group_id=1)


@pytest.fixture(autouse=True)
def _app_context(rest_api):
    """Pushes the app context so ManagerProvider resolves its database manager."""
    with rest_api.application.app_context():
        yield


@pytest.fixture(autouse=True)
def _seed(database_manager: MongoDatabaseManager, database_name: str):
    """Stores a type with a usable default, a legacy unusable one and a defaulted MDS field."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    types.delete_many({'public_id': TYPE_ID})
    fields: list[dict[str, Any]] = [
        {'type': 'text', 'name': NOTE_FIELD, 'label': 'Note', 'value': NOTE_DEFAULT},
        {'type': 'text', 'name': CODE_FIELD, 'label': 'Code', 'regex': '[A-Z]+', 'value': LEGACY_CODE_DEFAULT},
        {'type': 'text', 'name': ROW_FIELD, 'label': 'Row', 'value': ROW_DEFAULT},
    ]
    sections: list[dict[str, Any]] = [
        {'type': SectionType.SECTION.value, 'name': 'main', 'label': 'Main', 'fields': [NOTE_FIELD, CODE_FIELD]},
        {'type': SectionType.MDS_SECTION.value, 'name': MDS_SECTION, 'label': 'Rows', 'fields': [ROW_FIELD]},
    ]
    types.insert_one(make_type_doc(TYPE_ID, 'defaults-integration', fields=fields, sections=sections))
    yield
    types.delete_many({'public_id': TYPE_ID})


def _stored_type() -> CmdbType:
    """The type as the TypesManager reads it back."""
    types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, ADMIN)

    return CmdbType.from_data(types_manager.get_type(TYPE_ID))


class TestTheStoredType:
    """What the default rule sees on a type written before it existed."""

    def test_the_legacy_default_is_found(self) -> None:
        """The one the type write would now refuse on its next save"""
        assert list(find_default_value_errors(_stored_type().get_fields())) == [CODE_FIELD]


class TestTheRestCreateFill:
    """fill_object_defaults over the stored type."""

    def test_usable_defaults_are_filled_and_the_legacy_one_is_not(self) -> None:
        """The top-level list and a carried row; the unusable default stays out"""
        document: dict[str, Any] = {'fields': [], 'multi_data_sections': [
            {'section_id': MDS_SECTION, 'values': [{'multi_data_id': 1, 'data': []}]},
        ]}

        fill_object_defaults(document, _stored_type())

        assert {field['name']: field['value'] for field in document['fields']} == {NOTE_FIELD: NOTE_DEFAULT}
        assert document['multi_data_sections'][0]['values'][0]['data'][0]['value'] == ROW_DEFAULT


class TestTheImporterContext:
    """build_import_type_context over the stored type."""

    def test_the_context_offers_only_usable_defaults(self) -> None:
        """The same skip as the REST create"""
        context = build_import_type_context(_stored_type())

        assert context.top_level_field_defaults == {NOTE_FIELD: NOTE_DEFAULT, CODE_FIELD: None}
        assert context.mds_field_defaults_by_section == {MDS_SECTION: {ROW_FIELD: ROW_DEFAULT}}
