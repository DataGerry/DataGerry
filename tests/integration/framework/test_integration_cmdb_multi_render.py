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
Integration tests for CmdbMultiRender - the core object render

Renders a real object (with a text field, a reference field and a date field) against a real MongoDB,
pinning the render output that the whole application depends on: object/type information, merged field
values, date coercion, the expanded reference (object_id + referenced type), the summary line, and the
get_mds_reference / get_user_name helpers (incl. the fix that get_mds_reference always returns a dict).
"""
import logging
from datetime import datetime
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager
from cmdb.framework.rendering.cmdb_multi_render import CmdbMultiRender
from cmdb.framework.rendering.render_constants import ANONYMOUS_NAME
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

MAIN_TYPE_ID: int = 88101
REF_TYPE_ID: int = 88102
REFSEC_TYPE_ID: int = 88103
MAIN_OBJ_ID: int = 88111
REF_OBJ_ID: int = 88112
REFSEC_OBJ_ID: int = 88113
MAIN_OBJ_ID_2: int = 88114
REFSEC_OBJ_ID_NULL: int = 88115

NAME_FIELD: str = 'dg-name'
REF_FIELD: str = 'ref-field'
DATE_FIELD: str = 'date-field'
REFSEC_NAME: str = 'refsec'
REFSEC_REF_FIELD: str = 'refsec-field'  # the ref-section's implicit '<section>-field'

MAIN_NAME_VALUE: str = 'Main-Object'
MAIN_NAME_VALUE_2: str = 'Second-Object'
REF_NAME_VALUE: str = 'Ref-Target'
DATE_VALUE: str = '2024-01-02'

ALL_TYPE_IDS: list[int] = [MAIN_TYPE_ID, REF_TYPE_ID, REFSEC_TYPE_ID]
ALL_OBJ_IDS: list[int] = [MAIN_OBJ_ID, REF_OBJ_ID, REFSEC_OBJ_ID, MAIN_OBJ_ID_2, REFSEC_OBJ_ID_NULL]


@pytest.fixture(autouse=True)
def _render_context(rest_api):
    """Pushes the REST API app context so ManagerProvider (current_app.database_manager) resolves."""
    with rest_api.application.app_context():
        yield


def _main_type_doc() -> dict[str, Any]:
    """A type with a text, reference and date field, all surfaced by one section."""
    return make_type_doc(
        MAIN_TYPE_ID, 'render-main-type',
        fields=[
            {'type': 'text', 'name': NAME_FIELD, 'label': 'Name'},
            {'type': 'ref', 'name': REF_FIELD, 'label': 'Ref', 'ref_types': [REF_TYPE_ID]},
            {'type': 'date', 'name': DATE_FIELD, 'label': 'Date'},
        ],
        sections=[{'type': 'section', 'name': 'main', 'label': 'Main',
                   'fields': [NAME_FIELD, REF_FIELD, DATE_FIELD]}],
    )


def _ref_type_doc() -> dict[str, Any]:
    """A minimal referenced type with a single text field."""
    return make_type_doc(
        REF_TYPE_ID, 'render-ref-type',
        fields=[{'type': 'text', 'name': NAME_FIELD, 'label': 'Name'}],
        sections=[{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [NAME_FIELD]}],
    )


def _refsec_type_doc() -> dict[str, Any]:
    """A type with a reference-section pulling the ref type's 'main' section fields."""
    return make_type_doc(
        REFSEC_TYPE_ID, 'render-refsec-type',
        fields=[
            {'type': 'text', 'name': NAME_FIELD, 'label': 'Name'},
            {'type': 'ref', 'name': REFSEC_REF_FIELD, 'label': 'RefSec Ref', 'ref_types': [REF_TYPE_ID]},
        ],
        sections=[
            {'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [NAME_FIELD]},
            {'type': 'ref-section', 'name': REFSEC_NAME, 'label': 'Ref Section',
             'reference': {'type_id': REF_TYPE_ID, 'section_name': 'main', 'selected_fields': []},
             'fields': []},
        ],
    )


def _obj_doc(public_id: int, type_id: int, fields: list[dict[str, Any]]) -> dict[str, Any]:
    """A CmdbObject document for direct DB insertion."""
    return {
        'public_id': public_id,
        'type_id': type_id,
        'active': True,
        'author_id': 1,
        'version': '1.0.0',
        'fields': fields,
    }


@pytest.fixture(autouse=True)
def _seed(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the two types + two objects (main referencing ref), cleaning up after each test."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': {'$in': ALL_TYPE_IDS}})
        objects.delete_many({'public_id': {'$in': ALL_OBJ_IDS}})

    _purge()
    types.insert_many([_main_type_doc(), _ref_type_doc(), _refsec_type_doc()])
    objects.insert_many([
        _obj_doc(REF_OBJ_ID, REF_TYPE_ID, [{'type': 'text', 'name': NAME_FIELD, 'value': REF_NAME_VALUE}]),
        _obj_doc(MAIN_OBJ_ID, MAIN_TYPE_ID, [
            {'type': 'text', 'name': NAME_FIELD, 'value': MAIN_NAME_VALUE},
            {'type': 'ref', 'name': REF_FIELD, 'value': REF_OBJ_ID},
            {'type': 'date', 'name': DATE_FIELD, 'value': DATE_VALUE},
        ]),
        _obj_doc(REFSEC_OBJ_ID, REFSEC_TYPE_ID, [
            {'type': 'text', 'name': NAME_FIELD, 'value': 'Owner'},
            {'type': 'ref', 'name': REFSEC_REF_FIELD, 'value': REF_OBJ_ID},
        ]),
        _obj_doc(MAIN_OBJ_ID_2, MAIN_TYPE_ID, [
            {'type': 'text', 'name': NAME_FIELD, 'value': MAIN_NAME_VALUE_2},
            {'type': 'ref', 'name': REF_FIELD, 'value': REF_OBJ_ID},
            {'type': 'date', 'name': DATE_FIELD, 'value': DATE_VALUE},
        ]),
        # A refsec object with NO object referenced yet (value None) - mirrors an object cleaned
        # after a ref-section was added to its type
        _obj_doc(REFSEC_OBJ_ID_NULL, REFSEC_TYPE_ID, [
            {'type': 'text', 'name': NAME_FIELD, 'value': 'NoRef'},
            {'type': 'ref', 'name': REFSEC_REF_FIELD, 'value': None},
        ]),
    ])
    yield
    _purge()


def _field(fields: list[dict[str, Any]], name: str) -> dict[str, Any]:
    """Returns the rendered field with the given name."""
    return next(f for f in fields if f['name'] == name)


def _render_main(user, database_manager: MongoDatabaseManager, database_name: str, ref_render: bool = True):
    """Loads the main object and renders it."""
    doc = database_manager.get_collection(CmdbObject.COLLECTION, database_name).find_one({'public_id': MAIN_OBJ_ID})
    main_obj = CmdbObject.from_data(doc)
    return CmdbMultiRender([main_obj], user, ref_render)


class TestRenderResult:
    """result() renders object/type information, fields, references, dates and summaries."""

    def test_object_and_type_information(self, full_access_user,
                                         database_manager, database_name) -> None:
        """The object and type information blocks carry the expected ids and labels."""
        result = _render_main(full_access_user, database_manager, database_name).result(single_object=True)

        assert result.object_information['object_id'] == MAIN_OBJ_ID
        assert result.type_information['type_id'] == MAIN_TYPE_ID
        assert result.type_information['type_label'] == 'render-main-type'

    def test_text_field_value_and_summary_line(self, full_access_user,
                                               database_manager, database_name) -> None:
        """The text field keeps its value and drives the summary line."""
        result = _render_main(full_access_user, database_manager, database_name).result(single_object=True)

        assert _field(result.fields, NAME_FIELD)['value'] == MAIN_NAME_VALUE
        assert MAIN_NAME_VALUE in result.summary_line

    def test_date_field_is_parsed(self, full_access_user,
                                  database_manager, database_name) -> None:
        """A string date value is coerced to a datetime in the render."""
        result = _render_main(full_access_user, database_manager, database_name).result(single_object=True)

        assert isinstance(_field(result.fields, DATE_FIELD)['value'], datetime)

    def test_reference_field_is_expanded(self, full_access_user,
                                         database_manager, database_name) -> None:
        """The reference field expands to the referenced object_id and its type."""
        result = _render_main(full_access_user, database_manager, database_name).result(single_object=True)

        reference = _field(result.fields, REF_FIELD)['reference']
        assert reference['object_id'] == REF_OBJ_ID
        assert reference['type_id'] == REF_TYPE_ID

    def test_mds_reference_without_nested_line_renders_cleanly(self, full_access_user,
                                                              database_manager, database_name, caplog) -> None:
        """get_mds_reference for a ref with no nested summary line resolves with line=None, no log.

        Regression for the DEBUG-log spam: line_requires_fields' regex raised on a None line, which
        was caught and logged ("Could not fill summary line") for every such reference. Option A: no
        crash, no log, line stays None, and the reference still resolves (summaries clearing is the
        deferred Option B, so summaries stay a list here).
        """
        render = _render_main(full_access_user, database_manager, database_name)

        with caplog.at_level(logging.DEBUG, logger='cmdb.framework.rendering.cmdb_multi_render'):
            reference = render.get_mds_reference(REF_OBJ_ID)

        assert reference['object_id'] == REF_OBJ_ID
        assert reference['line'] is None
        assert isinstance(reference['summaries'], list)
        # The None-line no longer trips line_requires_fields' regex, so nothing is logged
        assert 'Could not fill summary line' not in caplog.text

    def test_render_without_ref_render_does_not_crash(self, full_access_user,
                                                      database_manager, database_name) -> None:
        """Rendering with ref_render=False still succeeds (guards the None-reference path)."""
        result = _render_main(full_access_user, database_manager, database_name, ref_render=False)\
            .result(single_object=True)

        assert _field(result.fields, NAME_FIELD)['value'] == MAIN_NAME_VALUE


class TestCacheIsolation:
    """Rendering multiple objects of one type keeps each result's values isolated (no cache bleed)."""

    def test_multiple_objects_same_type_keep_own_values(self, full_access_user,
                                                        database_manager, database_name) -> None:
        """Two objects of the same type render with their own field values, not a shared last-write."""
        collection = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        obj_a = CmdbObject.from_data(collection.find_one({'public_id': MAIN_OBJ_ID}))
        obj_b = CmdbObject.from_data(collection.find_one({'public_id': MAIN_OBJ_ID_2}))

        results = CmdbMultiRender([obj_a, obj_b], full_access_user, True).result()

        by_id = {r.object_information['object_id']: r for r in results}
        assert _field(by_id[MAIN_OBJ_ID].fields, NAME_FIELD)['value'] == MAIN_NAME_VALUE
        assert _field(by_id[MAIN_OBJ_ID_2].fields, NAME_FIELD)['value'] == MAIN_NAME_VALUE_2

    def test_render_does_not_mutate_type_cache(self, full_access_user,
                                               database_manager, database_name) -> None:
        """Rendering must not write object values back into the shared cached type field definitions."""
        render = _render_main(full_access_user, database_manager, database_name)
        render.result(single_object=True)

        cached_field = render.types_cache[MAIN_TYPE_ID].get_field(NAME_FIELD)
        assert 'value' not in cached_field

    def test_shared_cache_avoids_refetching_references(self, full_access_user, database_manager,
                                                       database_name, monkeypatch) -> None:
        """A nested render reusing the shared cache does not re-query an already-loaded reference."""
        requested: list[list[int]] = []
        original = ObjectsManager.get_objects_lookup

        def _spy(self, public_ids):
            requested.append(list(public_ids))
            return original(self, public_ids)

        monkeypatch.setattr(ObjectsManager, 'get_objects_lookup', _spy)

        # First render loads REF_OBJ_ID into the cache
        render = _render_main(full_access_user, database_manager, database_name)
        assert any(REF_OBJ_ID in batch for batch in requested)

        # A render sharing those caches must NOT ask the DB for REF_OBJ_ID again
        requested.clear()
        doc = database_manager.get_collection(CmdbObject.COLLECTION, database_name).find_one({'public_id': MAIN_OBJ_ID})
        CmdbMultiRender(
            [CmdbObject.from_data(doc)], full_access_user, True,
            shared_objects_cache=render.objects_cache,
            shared_types_cache=render.types_cache,
            shared_users_cache=render.users_cache,
        )
        assert all(REF_OBJ_ID not in batch for batch in requested)


class TestReferenceSection:
    """A ref-section pulls the referenced type's section fields into the render."""

    def test_reference_section_pulls_referenced_fields(self, full_access_user,
                                                       database_manager, database_name) -> None:
        """The ref-section resolves to the referenced type and merges its field values."""
        doc = database_manager.get_collection(CmdbObject.COLLECTION, database_name)\
            .find_one({'public_id': REFSEC_OBJ_ID})
        refsec_obj = CmdbObject.from_data(doc)

        result = CmdbMultiRender([refsec_obj], full_access_user, True).result(single_object=True)

        ref_field = _field(result.fields, REFSEC_REF_FIELD)
        assert ref_field['references']['type_id'] == REF_TYPE_ID
        merged = _field(ref_field['references']['fields'], NAME_FIELD)
        assert merged['value'] == REF_NAME_VALUE

    def test_ref_section_field_survives_when_no_object_is_referenced(self, full_access_user,
                                                                     database_manager, database_name) -> None:
        """Regression: a null-reference ref-section still emits its field so the frontend shows the section.

        The ref target type is loaded only via the ref-section scan here (no referenced object pulls it
        into the cache), so before the fix __merge_fields_value dropped the field and the section vanished.
        """
        doc = database_manager.get_collection(CmdbObject.COLLECTION, database_name)\
            .find_one({'public_id': REFSEC_OBJ_ID_NULL})
        refsec_obj = CmdbObject.from_data(doc)

        result = CmdbMultiRender([refsec_obj], full_access_user, True).result(single_object=True)

        ref_field = next((field for field in result.fields if field['name'] == REFSEC_REF_FIELD), None)
        assert ref_field is not None
        assert ref_field['value'] is None
        assert ref_field['references']['type_id'] == REF_TYPE_ID


class TestHelpers:
    """get_mds_reference and get_user_name behave per contract."""

    def test_get_mds_reference_resolves(self, full_access_user,
                                        database_manager, database_name) -> None:
        """get_mds_reference resolves a valid reference id to the referenced object/type."""
        render = _render_main(full_access_user, database_manager, database_name)

        reference = render.get_mds_reference(REF_OBJ_ID)
        assert isinstance(reference, dict)
        assert reference['object_id'] == REF_OBJ_ID
        assert reference['type_id'] == REF_TYPE_ID

    def test_get_mds_reference_falsy_returns_empty_dict(self, full_access_user,
                                                        database_manager, database_name) -> None:
        """get_mds_reference returns an (empty) dict - never None - for a falsy value."""
        render = _render_main(full_access_user, database_manager, database_name)

        reference = render.get_mds_reference(0)
        assert isinstance(reference, dict)
        assert reference['object_id'] == 0

    def test_get_user_name_anonymous_and_editor(self, full_access_user,
                                                database_manager, database_name) -> None:
        """A missing user_id yields the anonymous name, or None when resolving an editor."""
        render = _render_main(full_access_user, database_manager, database_name)

        assert render.get_user_name(None) == ANONYMOUS_NAME
        assert render.get_user_name(None, for_editor=True) is None
