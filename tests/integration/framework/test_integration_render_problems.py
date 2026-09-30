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
Integration tests for what a degraded render says about itself, against a real MongoDB

The stored documents are written straight into the collections, because each shape here is one the
write routes refuse today and a database can still hold: a section naming a field its type does not
declare, and a legacy untyped field its type has dropped. Also pins that a reference-section chain
is loaded one query per hop through the real ObjectsManager
"""
import logging
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager
from cmdb.framework.rendering.cmdb_multi_render import CmdbMultiRender
from cmdb.framework.rendering.render_constants import RenderProblemCode, RenderProblemKey
from cmdb.framework.rendering.render_result import RenderResult
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.type_model.field_type_enum import FieldType
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

GHOST_TYPE_ID: int = 88201
CLEAN_TYPE_ID: int = 88202
CHAIN_TYPE_ID: int = 88203

GHOST_OBJ_ID: int = 88211
CLEAN_OBJ_ID: int = 88212
DROPPED_OBJ_ID: int = 88213
CHAIN_START_ID: int = 88214
CHAIN_SECTION_TARGET_ID: int = 88215
CHAIN_NESTED_ID: int = 88216

NAME_FIELD: str = 'dg-name'
GHOST_FIELD: str = 'declared-by-no-type'
DROPPED_FIELD: str = 'dropped-from-the-type'
CHAIN_FIELD: str = 'chain-section-field'
SECTION_NAME: str = 'main'
NAME_VALUE: str = 'Stored-Name'

ALL_TYPE_IDS: list[int] = [GHOST_TYPE_ID, CLEAN_TYPE_ID, CHAIN_TYPE_ID]
ALL_OBJ_IDS: list[int] = [
    GHOST_OBJ_ID, CLEAN_OBJ_ID, DROPPED_OBJ_ID, CHAIN_START_ID, CHAIN_SECTION_TARGET_ID, CHAIN_NESTED_ID,
]


@pytest.fixture(autouse=True)
def _render_context(rest_api):
    """Pushes the REST API app context so ManagerProvider (current_app.database_manager) resolves."""
    with rest_api.application.app_context():
        yield


def _type_doc(type_id: int, section_fields: list[str]) -> dict[str, Any]:
    """A type declaring only NAME_FIELD, whose one section lists `section_fields`."""
    return make_type_doc(
        type_id, f'render-problems-{type_id}',
        fields=[{'type': FieldType.TEXT.value, 'name': NAME_FIELD, 'label': 'Name'}],
        sections=[{'type': 'section', 'name': SECTION_NAME, 'label': 'Main', 'fields': section_fields}],
    )


def _obj_doc(public_id: int, type_id: int, fields: list[dict[str, Any]]) -> dict[str, Any]:
    """A complete CmdbObject document for direct insertion."""
    return {
        'public_id': public_id, 'type_id': type_id, 'active': True, 'author_id': 1, 'version': '1.0.0',
        'creation_time': datetime.now(timezone.utc), 'fields': fields, 'multi_data_sections': [],
    }


def _name(value: str = NAME_VALUE) -> dict[str, Any]:
    """The stored NAME_FIELD entry."""
    return {'type': FieldType.TEXT.value, 'name': NAME_FIELD, 'value': value}


def _chain_link(target_id: int) -> dict[str, Any]:
    """A stored ref-section field pointing at `target_id`."""
    return {'type': FieldType.REF_SECTION.value, 'name': CHAIN_FIELD, 'value': target_id}


@pytest.fixture(autouse=True)
def _seed(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the types and objects straight into the collections; removes them after."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': {'$in': ALL_TYPE_IDS}})
        objects.delete_many({'public_id': {'$in': ALL_OBJ_IDS}})

    _purge()
    types.insert_many([
        _type_doc(GHOST_TYPE_ID, [NAME_FIELD, GHOST_FIELD]),
        _type_doc(CLEAN_TYPE_ID, [NAME_FIELD]),
        _type_doc(CHAIN_TYPE_ID, [NAME_FIELD]),
    ])
    objects.insert_many([
        _obj_doc(GHOST_OBJ_ID, GHOST_TYPE_ID, [_name()]),
        _obj_doc(CLEAN_OBJ_ID, CLEAN_TYPE_ID, [_name()]),
        _obj_doc(DROPPED_OBJ_ID, CLEAN_TYPE_ID, [_name(), {'name': DROPPED_FIELD, 'value': CLEAN_OBJ_ID}]),
        _obj_doc(CHAIN_START_ID, CHAIN_TYPE_ID, [_name(), _chain_link(CHAIN_SECTION_TARGET_ID)]),
        _obj_doc(CHAIN_SECTION_TARGET_ID, CHAIN_TYPE_ID, [_name(), _chain_link(CHAIN_NESTED_ID)]),
        _obj_doc(CHAIN_NESTED_ID, CHAIN_TYPE_ID, [_name()]),
    ])
    yield
    _purge()


def _load(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> CmdbObject:
    """Reads one stored object."""
    collection = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    return CmdbObject.from_data(collection.find_one({'public_id': public_id}))


def _render(user, database_manager, database_name, public_id: int, ref_render: bool = True) -> RenderResult:
    """Renders one stored object and answers its RenderResult."""
    results: list[RenderResult] = CmdbMultiRender(
        [_load(database_manager, database_name, public_id)], user, ref_render,
    ).result()

    assert len(results) == 1

    return results[0]


class TestAStoredSectionNamingAnUndeclaredField:
    """The section lists a field its type does not declare."""

    def test_the_field_is_left_out(self, full_access_user, database_manager, database_name) -> None:
        """The declared field renders; the undeclared one answers no entry"""
        result = _render(full_access_user, database_manager, database_name, GHOST_OBJ_ID)

        assert [field['name'] for field in result.fields] == [NAME_FIELD]

    def test_the_render_says_so(self, full_access_user, database_manager, database_name) -> None:
        """The loss is on the result, naming its section and field"""
        result = _render(full_access_user, database_manager, database_name, GHOST_OBJ_ID)

        assert result.render_problems == [{
            RenderProblemKey.CODE.value: RenderProblemCode.FIELD_NOT_ON_TYPE.value,
            RenderProblemKey.SECTION.value: SECTION_NAME,
            RenderProblemKey.FIELD.value: GHOST_FIELD,
            RenderProblemKey.EXTERNAL_LINK.value: None,
        }]

    def test_a_complete_render_says_nothing(self, full_access_user, database_manager, database_name) -> None:
        """The control: a well-formed type and object render with no problems"""
        assert _render(full_access_user, database_manager, database_name, CLEAN_OBJ_ID).render_problems == []


class TestALegacyFieldItsTypeDropped:
    """An untyped stored field naming a field the type no longer declares."""

    def test_the_object_still_renders(self, full_access_user, database_manager, database_name, caplog) -> None:
        """The reference collection skips the row - the render is built, complete, and the row logged"""
        with caplog.at_level(logging.WARNING):
            result = _render(full_access_user, database_manager, database_name, DROPPED_OBJ_ID)

        assert [field['value'] for field in result.fields] == [NAME_VALUE]
        assert result.render_problems == []
        assert DROPPED_FIELD in caplog.text


class TestReferenceChainPrefetch:
    """A reference-section chain is loaded one query per hop, before the render starts."""

    def test_the_chain_is_cached_in_two_queries(
        self,
        full_access_user,
        database_manager: MongoDatabaseManager,
        database_name: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The section target in the first query, the nested target behind it in the second"""
        requested: list[set[int]] = []
        original = ObjectsManager.get_objects_lookup

        def _spy(manager: ObjectsManager, public_ids: list[int]) -> dict[int, CmdbObject]:
            requested.append(set(public_ids))
            return original(manager, public_ids)

        monkeypatch.setattr(ObjectsManager, 'get_objects_lookup', _spy)

        render = CmdbMultiRender([_load(database_manager, database_name, CHAIN_START_ID)], full_access_user, True)

        assert requested == [{CHAIN_SECTION_TARGET_ID}, {CHAIN_NESTED_ID}]
        assert {CHAIN_SECTION_TARGET_ID, CHAIN_NESTED_ID} <= set(render.objects_cache)
