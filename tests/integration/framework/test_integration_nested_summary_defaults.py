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
Integration tests for a reference field's nested summary with a missing key, against a real MongoDB

The type import stores a nested-summary entry as it was sent, and a direct write can too, so a stored
entry may lack `prefix`, `fields` or `line`. Each is rendered here through `CmdbMultiRender` from the
stored documents: the missing key is its default - the schema's `prefix`, no fields, no line - and the
reference renders instead of degrading to an icon and a label, with nothing logged
"""
import logging
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.rendering.cmdb_multi_render import CmdbMultiRender
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.type_model.type_constants import NESTED_SUMMARY_PREFIX_DEFAULT
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

TARGET_TYPE_ID: int = 93930
TARGET_OBJECT_ID: int = 93931

NAME_FIELD: str = 'target-name'
TARGET_NAME: str = 'core-switch-01'
REF_FIELD: str = 'uplink'
PLACEHOLDER_LINE: str = 'Device {}'
STATIC_LINE: str = 'See the rack plan'

# One referring type + object per case: (type id, object id, the stored nested-summary entry)
CASES: dict[str, tuple[int, int, dict[str, Any]]] = {
    'no prefix': (93932, 93933, {'type_id': TARGET_TYPE_ID, 'line': PLACEHOLDER_LINE, 'fields': [NAME_FIELD]}),
    'no fields': (93934, 93935, {'type_id': TARGET_TYPE_ID, 'line': STATIC_LINE, 'prefix': False}),
    'no line': (93936, 93937, {'type_id': TARGET_TYPE_ID, 'fields': [NAME_FIELD], 'prefix': False}),
}
TYPE_IDS: list[int] = [TARGET_TYPE_ID, *(type_id for type_id, _, _ in CASES.values())]
OBJECT_IDS: list[int] = [TARGET_OBJECT_ID, *(object_id for _, object_id, _ in CASES.values())]


def _object_doc(public_id: int, type_id: int, fields: list[dict[str, Any]]) -> dict[str, Any]:
    """A CmdbObject document for direct insertion."""
    return {'public_id': public_id, 'type_id': type_id, 'active': True, 'author_id': 1, 'version': '1.0.0',
            'fields': fields}


@pytest.fixture(autouse=True)
def _seed(rest_api, database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the target and one referring type + object per case, inside the app context the render needs."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': {'$in': TYPE_IDS}})
        objects.delete_many({'public_id': {'$in': OBJECT_IDS}})

    _purge()
    types.insert_one(make_type_doc(
        TARGET_TYPE_ID, 'nested-summary-target',
        fields=[{'type': 'text', 'name': NAME_FIELD, 'label': 'Name'}],
        sections=[{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [NAME_FIELD]}],
    ))
    objects.insert_one(_object_doc(TARGET_OBJECT_ID, TARGET_TYPE_ID, [{'name': NAME_FIELD, 'value': TARGET_NAME}]))

    for type_id, object_id, entry in CASES.values():
        types.insert_one(make_type_doc(
            type_id, f'nested-summary-{type_id}',
            fields=[{'type': 'ref', 'name': REF_FIELD, 'label': 'Uplink', 'ref_types': [TARGET_TYPE_ID],
                     'summaries': [entry]}],
            sections=[{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [REF_FIELD]}],
        ))
        objects.insert_one(_object_doc(object_id, type_id, [{'type': 'ref', 'name': REF_FIELD,
                                                              'value': TARGET_OBJECT_ID}]))

    with rest_api.application.app_context():
        yield

    _purge()


def _reference(case: str, user, database_manager: MongoDatabaseManager, database_name: str,
               caplog) -> dict[str, Any]:
    """Renders the case's referring object from the stored documents; no WARNING allowed on the way."""
    _, object_id, _ = CASES[case]
    stored = database_manager.get_collection(CmdbObject.COLLECTION, database_name).find_one({'public_id': object_id})

    with caplog.at_level(logging.WARNING):
        result = CmdbMultiRender([CmdbObject.from_data(stored)], user, True).result(single_object=True)

    assert '_merge_references' not in caplog.text

    return next(field for field in result.fields if field['name'] == REF_FIELD)['reference']


def test_an_entry_without_prefix_renders_with_the_schema_default(full_access_user, database_manager,
                                                                 database_name, caplog) -> None:
    """The line is filled and `prefix` is what the type route would have stored"""
    reference = _reference('no prefix', full_access_user, database_manager, database_name, caplog)

    assert reference['prefix'] is NESTED_SUMMARY_PREFIX_DEFAULT
    assert reference['line'] == PLACEHOLDER_LINE.format(TARGET_NAME)


def test_an_entry_without_fields_renders_its_line(full_access_user, database_manager, database_name,
                                                  caplog) -> None:
    """No `fields` is an empty list, so a static line is shown as it is"""
    reference = _reference('no fields', full_access_user, database_manager, database_name, caplog)

    assert reference['line'] == STATIC_LINE
    assert reference['object_id'] == TARGET_OBJECT_ID


def test_an_entry_without_a_line_renders_its_summary_fields(full_access_user, database_manager, database_name,
                                                            caplog) -> None:
    """No `line` is no line: the summaries carry the referenced object's value"""
    reference = _reference('no line', full_access_user, database_manager, database_name, caplog)

    assert reference['line'] is None
    assert [summary['value'] for summary in reference['summaries']] == [TARGET_NAME]
