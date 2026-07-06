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
Functional smoke for the ``/ci_explorer`` CRUD + tooltip / type_label REST routes

Covers the route-layer concerns the manager suites cannot: the profile create / list / update /
delete status codes, the update-route public_id pinning, and the ``/tooltip`` + ``/type_label``
routes that read their value from the request body and persist it (the regression guard for the
missing body-injection bug). The CI Explorer graph route (``/items``) is covered separately.
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import CiExplorerProfileManager, ObjectsManager, TypesManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.ci_explorer_model import CmdbCiExplorerProfile
from cmdb.errors.manager.ci_explorer_profile_manager import (
    CiExplorerProfileManagerInsertError,
    CiExplorerProfileManagerGetError,
    CiExplorerProfileManagerUpdateError,
    CiExplorerProfileManagerDeleteError,
    CiExplorerProfileManagerIterationError,
)
from cmdb.errors.manager.objects_manager import ObjectsManagerGetError, ObjectsManagerUpdateError
from cmdb.errors.manager.types_manager import TypesManagerGetError, TypesManagerUpdateError
import cmdb.interface.rest_api.routes.ci_explorer_routes.ci_explorer_routes as ci_explorer_routes_module
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/ci_explorer'

PROFILE_FOR_CREATE: int = 9910
PROFILE_FOR_UPDATE: int = 9911
PROFILE_FOR_DELETE: int = 9912
PROFILE_MISMATCH_PAYLOAD_ID: int = 9913

TYPE_FOR_TOOLTIP: int = 9920
OBJECT_FOR_TOOLTIP: int = 9921
TYPE_FOR_LABEL: int = 9922
MISSING_ID: int = 9999

ALL_PROFILE_IDS: list[int] = [
    PROFILE_FOR_CREATE, PROFILE_FOR_UPDATE, PROFILE_FOR_DELETE, PROFILE_MISMATCH_PAYLOAD_ID,
]

ORIGINAL_NAME: str = 'Original Profile'
UPDATED_NAME: str = 'Updated Profile'
TOOLTIP_TEXT: str = 'A helpful tooltip'
LABEL_TEXT: str = 'name'


def _profile_payload(public_id: int, name: str = ORIGINAL_NAME) -> dict[str, Any]:
    """Builds a CmdbCiExplorerProfile payload acceptable to POST / PUT (and to direct DB insertion)."""
    return {
        'public_id': public_id,
        'name': name,
        'types_filter': [],
        'relations_filter': [],
        'with_locations': True,
        'with_ipam_relations': False,
    }


def _type_doc(public_id: int) -> dict[str, Any]:
    """Builds a minimal active CmdbType doc (update_object / update_type require an active type)."""
    return {
        'public_id': public_id,
        'name': f'ci-explorer-type-{public_id}',
        'label': 'CI Explorer Type',
        'author_id': 1,
        'active': True,
        'fields': [{'type': 'text', 'name': 'name', 'label': 'Name'}],
        'render_meta': {
            'icon': 'fa-cube',
            'sections': [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': ['name']}],
            'summary': {'fields': ['name']},
        },
        'ci_explorer_label': 'name',
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': '1.0.0',
        'creation_time': datetime.now(timezone.utc),
    }


def _object_doc(public_id: int, type_id: int) -> dict[str, Any]:
    """Builds a minimal CmdbObject doc of the given type."""
    return {
        'public_id': public_id,
        'type_id': type_id,
        'active': True,
        'author_id': 1,
        'version': '1.0.0',
        'fields': [{'type': 'text', 'name': 'name', 'value': 'obj'}],
        'creation_time': datetime.now(timezone.utc),
    }


def _profiles(database_manager: MongoDatabaseManager, database_name: str):
    """Returns the CmdbCiExplorerProfile collection bound to the test database."""
    return database_manager.get_collection(CmdbCiExplorerProfile.COLLECTION, database_name)


@pytest.fixture(scope='module', autouse=True)
def _cleanup_profiles(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any leftover test profiles after the module's tests have run."""
    yield
    _profiles(database_manager, database_name).delete_many({'public_id': {'$in': ALL_PROFILE_IDS}})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    PROFILE CRUD                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestProfileCrud:
    """POST / GET / PUT / DELETE on /ci_explorer/profile."""

    def test_create_then_list_contains_it(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A POST creates a profile and a follow-up list returns the envelope including it."""
        try:
            response = rest_api.post(f'{ROUTE_URL}/profile', json=_profile_payload(PROFILE_FOR_CREATE))

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)

            listing = rest_api.get(f'{ROUTE_URL}/profile')
            assert listing.status_code == HTTPStatus.OK
            assert 'results' in listing.get_json()
        finally:
            _profiles(database_manager, database_name).delete_one({'public_id': PROFILE_FOR_CREATE})

    def test_update_persists_new_name(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """After PUT, the stored profile carries the updated name."""
        collection = _profiles(database_manager, database_name)
        collection.insert_one(_profile_payload(PROFILE_FOR_UPDATE))
        try:
            response = rest_api.put(
                f'{ROUTE_URL}/profile/{PROFILE_FOR_UPDATE}',
                json=_profile_payload(PROFILE_FOR_UPDATE, UPDATED_NAME),
            )

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
            assert collection.find_one({'public_id': PROFILE_FOR_UPDATE})['name'] == UPDATED_NAME
        finally:
            collection.delete_one({'public_id': PROFILE_FOR_UPDATE})

    def test_update_pins_public_id_to_the_url(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A payload public_id different from the URL cannot rewrite the document's identity."""
        collection = _profiles(database_manager, database_name)
        collection.insert_one(_profile_payload(PROFILE_FOR_UPDATE))
        try:
            response = rest_api.put(
                f'{ROUTE_URL}/profile/{PROFILE_FOR_UPDATE}',
                json=_profile_payload(PROFILE_MISMATCH_PAYLOAD_ID, UPDATED_NAME),
            )

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
            # The document keeps its URL id and is updated in place ...
            assert collection.find_one({'public_id': PROFILE_FOR_UPDATE})['name'] == UPDATED_NAME
            # ... and no shadow document is created under the payload's id.
            assert collection.find_one({'public_id': PROFILE_MISMATCH_PAYLOAD_ID}) is None
        finally:
            collection.delete_one({'public_id': PROFILE_FOR_UPDATE})
            collection.delete_one({'public_id': PROFILE_MISMATCH_PAYLOAD_ID})

    def test_update_missing_returns_404(self, rest_api) -> None:
        """PUT against a missing profile id returns 404."""
        response = rest_api.put(
            f'{ROUTE_URL}/profile/{MISSING_ID}', json=_profile_payload(MISSING_ID, UPDATED_NAME),
        )

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_delete_removes_profile(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A DELETE removes the profile from the collection."""
        collection = _profiles(database_manager, database_name)
        collection.insert_one(_profile_payload(PROFILE_FOR_DELETE))
        try:
            response = rest_api.delete(f'{ROUTE_URL}/profile/{PROFILE_FOR_DELETE}')

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
            assert collection.find_one({'public_id': PROFILE_FOR_DELETE}) is None
            # The deleted profile is returned in the canonical to_json shape (not the model __dict__)
            deleted = response.json['raw']
            assert deleted['public_id'] == PROFILE_FOR_DELETE
            assert set(deleted) == {
                'public_id', 'name', 'types_filter', 'relations_filter',
                'with_locations', 'with_ipam_relations',
            }
        finally:
            collection.delete_one({'public_id': PROFILE_FOR_DELETE})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  TOOLTIP / LABEL                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTooltipAndTypeLabel:
    """PUT /ci_explorer/tooltip/<id> and /type_label/<id> read the body and persist the value."""

    def test_update_tooltip_persists_value(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """PUT /tooltip sets ci_explorer_tooltip on the object and returns the persisted value."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        types.insert_one(_type_doc(TYPE_FOR_TOOLTIP))
        objects.insert_one(_object_doc(OBJECT_FOR_TOOLTIP, TYPE_FOR_TOOLTIP))
        try:
            response = rest_api.put(
                f'{ROUTE_URL}/tooltip/{OBJECT_FOR_TOOLTIP}',
                json={'ci_explorer_tooltip': TOOLTIP_TEXT},
            )

            assert response.status_code == HTTPStatus.OK
            stored = objects.find_one({'public_id': OBJECT_FOR_TOOLTIP})
            assert stored['ci_explorer_tooltip'] == TOOLTIP_TEXT
        finally:
            objects.delete_one({'public_id': OBJECT_FOR_TOOLTIP})
            types.delete_one({'public_id': TYPE_FOR_TOOLTIP})

    def test_update_tooltip_missing_body_returns_400(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """PUT /tooltip without the tooltip key is rejected with 400 instead of silently writing None."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        types.insert_one(_type_doc(TYPE_FOR_TOOLTIP))
        objects.insert_one(_object_doc(OBJECT_FOR_TOOLTIP, TYPE_FOR_TOOLTIP))
        try:
            response = rest_api.put(f'{ROUTE_URL}/tooltip/{OBJECT_FOR_TOOLTIP}', json={})

            assert response.status_code == HTTPStatus.BAD_REQUEST
        finally:
            objects.delete_one({'public_id': OBJECT_FOR_TOOLTIP})
            types.delete_one({'public_id': TYPE_FOR_TOOLTIP})

    def test_update_tooltip_missing_object_returns_404(self, rest_api) -> None:
        """PUT /tooltip for a missing object returns 404."""
        response = rest_api.put(f'{ROUTE_URL}/tooltip/{MISSING_ID}', json={'ci_explorer_tooltip': TOOLTIP_TEXT})

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_update_type_label_persists_value(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """PUT /type_label sets ci_explorer_label on the type and returns the persisted value."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        types.insert_one(_type_doc(TYPE_FOR_LABEL))
        try:
            response = rest_api.put(
                f'{ROUTE_URL}/type_label/{TYPE_FOR_LABEL}',
                json={'ci_explorer_label': LABEL_TEXT},
            )

            assert response.status_code == HTTPStatus.OK
            assert types.find_one({'public_id': TYPE_FOR_LABEL})['ci_explorer_label'] == LABEL_TEXT
        finally:
            types.delete_one({'public_id': TYPE_FOR_LABEL})

    def test_update_type_label_missing_body_returns_400(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """PUT /type_label without the label key is rejected with 400."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        types.insert_one(_type_doc(TYPE_FOR_LABEL))
        try:
            assert rest_api.put(
                f'{ROUTE_URL}/type_label/{TYPE_FOR_LABEL}', json={},
            ).status_code == HTTPStatus.BAD_REQUEST
        finally:
            types.delete_one({'public_id': TYPE_FOR_LABEL})

    def test_update_type_label_missing_type_returns_404(self, rest_api) -> None:
        """PUT /type_label for a missing type returns 404."""
        assert rest_api.put(
            f'{ROUTE_URL}/type_label/{MISSING_ID}', json={'ci_explorer_label': LABEL_TEXT},
        ).status_code == HTTPStatus.NOT_FOUND


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  ERROR MAPPING                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def _raiser(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


class TestErrorMapping:
    """Manager failures map to 400 (typed) / 500 (unexpected) across the CI Explorer routes."""

    def test_insert_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A CiExplorerProfileManagerInsertError on create surfaces as 400."""
        monkeypatch.setattr(CiExplorerProfileManager, 'insert_item',
                            _raiser(CiExplorerProfileManagerInsertError('boom')))

        assert rest_api.post(f'{ROUTE_URL}/profile',
                             json=_profile_payload(PROFILE_FOR_CREATE)).status_code == HTTPStatus.BAD_REQUEST

    def test_insert_created_retrieval_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A get error while re-reading the created profile surfaces as 400."""
        monkeypatch.setattr(CiExplorerProfileManager, 'insert_item', lambda *_a, **_k: 999)
        monkeypatch.setattr(CiExplorerProfileManager, 'get_item',
                            _raiser(CiExplorerProfileManagerGetError('boom')))

        assert rest_api.post(f'{ROUTE_URL}/profile',
                             json=_profile_payload(PROFILE_FOR_CREATE)).status_code == HTTPStatus.BAD_REQUEST

    def test_insert_created_retrieval_none_returns_404(self, rest_api, monkeypatch) -> None:
        """A None result while re-reading the created profile surfaces as 404."""
        monkeypatch.setattr(CiExplorerProfileManager, 'insert_item', lambda *_a, **_k: 999)
        monkeypatch.setattr(CiExplorerProfileManager, 'get_item', lambda *_a, **_k: None)

        assert rest_api.post(f'{ROUTE_URL}/profile',
                             json=_profile_payload(PROFILE_FOR_CREATE)).status_code == HTTPStatus.NOT_FOUND

    def test_insert_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on create surfaces as 500."""
        monkeypatch.setattr(CiExplorerProfileManager, 'insert_item', _raiser(RuntimeError('boom')))

        assert rest_api.post(f'{ROUTE_URL}/profile',
                             json=_profile_payload(PROFILE_FOR_CREATE)).status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_list_iteration_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A CiExplorerProfileManagerIterationError on list surfaces as 400."""
        monkeypatch.setattr(CiExplorerProfileManager, 'iterate_items',
                            _raiser(CiExplorerProfileManagerIterationError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/profile').status_code == HTTPStatus.BAD_REQUEST

    def test_list_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on list surfaces as 500."""
        monkeypatch.setattr(CiExplorerProfileManager, 'iterate_items', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/profile').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_update_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A get error while loading the profile to update surfaces as 400."""
        monkeypatch.setattr(CiExplorerProfileManager, 'get_item',
                            _raiser(CiExplorerProfileManagerGetError('boom')))

        assert rest_api.put(f'{ROUTE_URL}/profile/{PROFILE_FOR_UPDATE}',
                            json=_profile_payload(PROFILE_FOR_UPDATE)).status_code == HTTPStatus.BAD_REQUEST

    def test_update_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A CiExplorerProfileManagerUpdateError on update surfaces as 400."""
        monkeypatch.setattr(CiExplorerProfileManager, 'get_item', lambda *_a, **_k: {'public_id': PROFILE_FOR_UPDATE})
        monkeypatch.setattr(CiExplorerProfileManager, 'update_item',
                            _raiser(CiExplorerProfileManagerUpdateError('boom')))

        assert rest_api.put(f'{ROUTE_URL}/profile/{PROFILE_FOR_UPDATE}',
                            json=_profile_payload(PROFILE_FOR_UPDATE)).status_code == HTTPStatus.BAD_REQUEST

    def test_update_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on update surfaces as 500."""
        monkeypatch.setattr(CiExplorerProfileManager, 'get_item', lambda *_a, **_k: {'public_id': PROFILE_FOR_UPDATE})
        monkeypatch.setattr(CiExplorerProfileManager, 'update_item', _raiser(RuntimeError('boom')))

        assert rest_api.put(f'{ROUTE_URL}/profile/{PROFILE_FOR_UPDATE}',
                            json=_profile_payload(PROFILE_FOR_UPDATE)).status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_delete_missing_returns_404(self, rest_api) -> None:
        """DELETE against a missing profile id returns 404."""
        assert rest_api.delete(f'{ROUTE_URL}/profile/{MISSING_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_delete_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A get error while loading the profile to delete surfaces as 400."""
        monkeypatch.setattr(CiExplorerProfileManager, 'get_item',
                            _raiser(CiExplorerProfileManagerGetError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/profile/{PROFILE_FOR_DELETE}').status_code == HTTPStatus.BAD_REQUEST

    def test_delete_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A CiExplorerProfileManagerDeleteError on delete surfaces as 400."""
        monkeypatch.setattr(CiExplorerProfileManager, 'get_item', lambda *_a, **_k: object())
        monkeypatch.setattr(CiExplorerProfileManager, 'delete_item',
                            _raiser(CiExplorerProfileManagerDeleteError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/profile/{PROFILE_FOR_DELETE}').status_code == HTTPStatus.BAD_REQUEST

    def test_delete_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on delete surfaces as 500."""
        monkeypatch.setattr(CiExplorerProfileManager, 'get_item', lambda *_a, **_k: object())
        monkeypatch.setattr(CiExplorerProfileManager, 'delete_item', _raiser(RuntimeError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/profile/{PROFILE_FOR_DELETE}').status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_tooltip_manager_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectsManager error while updating the tooltip surfaces as 400."""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(ObjectsManagerGetError('boom')))

        assert rest_api.put(f'{ROUTE_URL}/tooltip/{OBJECT_FOR_TOOLTIP}',
                            json={'ci_explorer_tooltip': TOOLTIP_TEXT}).status_code == HTTPStatus.BAD_REQUEST

    def test_tooltip_update_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectsManagerUpdateError while persisting the tooltip surfaces as 400."""
        monkeypatch.setattr(ObjectsManager, 'get_object', lambda *_a, **_k: {'public_id': OBJECT_FOR_TOOLTIP})
        monkeypatch.setattr(ObjectsManager, 'update_object', _raiser(ObjectsManagerUpdateError('boom')))

        assert rest_api.put(f'{ROUTE_URL}/tooltip/{OBJECT_FOR_TOOLTIP}',
                            json={'ci_explorer_tooltip': TOOLTIP_TEXT}).status_code == HTTPStatus.BAD_REQUEST

    def test_tooltip_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error while updating the tooltip surfaces as 500."""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(RuntimeError('boom')))

        assert rest_api.put(f'{ROUTE_URL}/tooltip/{OBJECT_FOR_TOOLTIP}',
                            json={'ci_explorer_tooltip': TOOLTIP_TEXT}).status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_type_label_manager_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A TypesManager error while updating the label surfaces as 400."""
        monkeypatch.setattr(TypesManager, 'get_type', _raiser(TypesManagerGetError('boom')))

        assert rest_api.put(f'{ROUTE_URL}/type_label/{TYPE_FOR_LABEL}',
                            json={'ci_explorer_label': LABEL_TEXT}).status_code == HTTPStatus.BAD_REQUEST

    def test_type_label_update_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A TypesManagerUpdateError while persisting the label surfaces as 400."""
        monkeypatch.setattr(TypesManager, 'get_type', lambda *_a, **_k: {'public_id': TYPE_FOR_LABEL})
        monkeypatch.setattr(TypesManager, 'update_type', _raiser(TypesManagerUpdateError('boom')))

        assert rest_api.put(f'{ROUTE_URL}/type_label/{TYPE_FOR_LABEL}',
                            json={'ci_explorer_label': LABEL_TEXT}).status_code == HTTPStatus.BAD_REQUEST

    def test_type_label_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error while updating the label surfaces as 500."""
        monkeypatch.setattr(TypesManager, 'get_type', _raiser(RuntimeError('boom')))

        assert rest_api.put(f'{ROUTE_URL}/type_label/{TYPE_FOR_LABEL}',
                            json={'ci_explorer_label': LABEL_TEXT}).status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_items_missing_target_id_returns_400(self, rest_api) -> None:
        """GET /items without target_id is rejected with 400 (argparsing abort, re-raised)."""
        assert rest_api.get(f'{ROUTE_URL}/items').status_code == HTTPStatus.BAD_REQUEST

    def test_items_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error while building the graph surfaces as 500."""
        monkeypatch.setattr(ci_explorer_routes_module, 'build_ci_explorer_graph', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/items?target_id=1').status_code == HTTPStatus.INTERNAL_SERVER_ERROR
