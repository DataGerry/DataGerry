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
Integration tests for the order in which a report write judges its type, against a real MongoDB

The write payload is built through the real ``ReportsManager`` from stored types with real ACLs and real fields:

  - over a type the caller may not READ, a payload naming its Ref-Section-Field or a value its number field cannot
    take is the 403 - the guards that describe the type's fields never run
  - over a readable type the same payloads are the 400s that name the field
  - an update that keeps its type builds from the document the stored-report check read, with the same result
"""
from typing import Any

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.database import MongoDatabaseManager
from cmdb.database.mongo_query_builder import RULE_VALUE_EXPECTS_WHOLE_NUMBER, RULE_VALUE_MISFIT_MSG
from cmdb.errors.mongo_query_builder import MongoQueryBuilderBuildRuleError
from cmdb.manager import ReportsManager
from cmdb.models.reports_model.cmdb_report_category import CmdbReportCategory
from cmdb.models.type_model import CmdbType
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.routes.report_routes.report_constants import REPORT_TARGET_TYPE_ACCESS_DENIED_MSG
from cmdb.interface.rest_api.routes.report_routes.report_helper import (
    abort_unless_report_readable,
    build_report_create_payload,
    build_report_update_payload,
)

from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

READER_GROUP_ID: int = 1
OTHER_GROUP_ID: int = 2
READABLE_TYPE_ID: int = 98131
DENIED_TYPE_ID: int = 98132
CATEGORY_ID: int = 98133
REPORT_ID: int = 98134
REF_SECTION_FIELD: str = 'order-refsec'
NUMBER_FIELD: str = 'order-num'
NOT_A_NUMBER: str = 'abc'
HTTP_BAD_REQUEST: int = 400
HTTP_FORBIDDEN: int = 403

READER: CmdbUser = CmdbUser(public_id=1, user_name='report-order-reader', active=True, group_id=READER_GROUP_ID)
FIELDS: list[dict[str, Any]] = [
    {'type': FieldType.TEXT.value, 'name': 'dg-name', 'label': 'Name'},
    {'type': FieldType.REF_SECTION.value, 'name': REF_SECTION_FIELD, 'label': 'Section'},
    {'type': FieldType.NUMBER.value, 'name': NUMBER_FIELD, 'label': 'Number'},
]


def _type(public_id: int, granted_group: int) -> dict[str, Any]:
    """A type with the probe fields whose activated ACL grants READ to one group"""
    return {
        **make_type_doc(public_id, f'report-order-{public_id}', fields=FIELDS),
        'acl': {'activated': True, 'groups': {'includes': {str(granted_group): ['READ']}}},
    }


def _params(type_id: int, **overrides: Any) -> dict[str, Any]:
    """A write payload over a type, as a JSON body sends it"""
    return {
        'report_category_id': CATEGORY_ID, 'name': 'report-order', 'type_id': type_id,
        'selected_fields': ['dg-name'], 'conditions': {'condition': 'and', 'rules': []}, 'mds_mode': 'ROWS',
        **overrides,
    }


def _number_rule() -> dict[str, Any]:
    """A condition comparing the number field to a value it cannot take"""
    return {'condition': 'and', 'rules': [{'field': NUMBER_FIELD, 'operator': '=', 'value': NOT_A_NUMBER}]}


PROBES: dict[str, dict[str, Any]] = {
    'ref-section-field': {'selected_fields': [REF_SECTION_FIELD]},
    'number-field-value': {'conditions': _number_rule()},
}


@pytest.fixture(name='manager')
def fixture_manager(database_manager: MongoDatabaseManager, database_name: str):
    """A readable and a denied type and a category, purged before and after"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    categories = database_manager.get_collection(CmdbReportCategory.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': {'$in': [READABLE_TYPE_ID, DENIED_TYPE_ID]}})
        categories.delete_many({'public_id': CATEGORY_ID})

    _purge()
    types.insert_many([_type(READABLE_TYPE_ID, READER_GROUP_ID), _type(DENIED_TYPE_ID, OTHER_GROUP_ID)])
    categories.insert_one({'public_id': CATEGORY_ID, 'name': 'report-order', 'predefined': False})

    yield ReportsManager(database_manager)

    _purge()


@pytest.mark.parametrize('overrides', PROBES.values(), ids=PROBES.keys())
def test_a_probe_of_a_denied_type_is_the_403(manager: ReportsManager, overrides: dict[str, Any]) -> None:
    """Never the 400 that would name the field or tell its type"""
    with pytest.raises(HTTPException) as exc_info:
        build_report_create_payload(manager, _params(DENIED_TYPE_ID, **overrides), READER)

    assert exc_info.value.code == HTTP_FORBIDDEN
    assert exc_info.value.description == REPORT_TARGET_TYPE_ACCESS_DENIED_MSG.format(type_id=DENIED_TYPE_ID)


def test_a_readable_type_names_its_ref_section_field(manager: ReportsManager) -> None:
    """The reader may know it"""
    with pytest.raises(HTTPException) as exc_info:
        build_report_create_payload(manager, _params(READABLE_TYPE_ID, **PROBES['ref-section-field']), READER)

    assert exc_info.value.code == HTTP_BAD_REQUEST
    assert REF_SECTION_FIELD in exc_info.value.description


def test_a_readable_type_names_the_misfit_value(manager: ReportsManager) -> None:
    """The builder's message names the field and what it takes"""
    with pytest.raises(MongoQueryBuilderBuildRuleError) as exc_info:
        build_report_create_payload(manager, _params(READABLE_TYPE_ID, **PROBES['number-field-value']), READER)

    assert str(exc_info.value) == RULE_VALUE_MISFIT_MSG.format(
        value=NOT_A_NUMBER, field=NUMBER_FIELD, expected=RULE_VALUE_EXPECTS_WHOLE_NUMBER,
    )


def test_an_update_builds_the_same_from_the_stored_type(manager: ReportsManager) -> None:
    """The document the stored-report check read stands in for the second read - the payload is the same"""
    stored_report: dict[str, Any] = {'public_id': REPORT_ID, 'type_id': READABLE_TYPE_ID, 'predefined': False}
    stored_type: dict[str, Any] | None = abort_unless_report_readable(manager, stored_report, READER)

    reused: dict[str, Any] = build_report_update_payload(
        manager, _params(READABLE_TYPE_ID), REPORT_ID, stored_report, READER, stored_type,
    )
    read_again: dict[str, Any] = build_report_update_payload(
        manager, _params(READABLE_TYPE_ID), REPORT_ID, stored_report, READER,
    )

    assert stored_type is not None and stored_type['public_id'] == READABLE_TYPE_ID
    assert reused == read_again
