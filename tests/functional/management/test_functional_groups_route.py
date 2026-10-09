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
Functional smoke for the ``/groups`` REST routes

Covers the route-layer concerns that the GroupsManager integration suite cannot: HTTP status
codes, the 404 on a missing id, the JSON envelopes, the list answering the single read's rights,
the PUT round-trip, the DELETE status (202), and the DELETE delete-mode matrix (None / MOVE+missing group_id→400 /
MOVE+target / DELETE+admin-in-group→400 / protected-group→400). CRUD behavior itself is asserted at the manager
layer; these tests verify that the route wraps it correctly and that the recent bug fixes
to the delete-mode flow hold
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import GroupsManager, UsersManager
from cmdb.models.group_model import (
    CmdbUserGroup,
    GroupDeleteMode,
    ADMIN_GROUP_ID,
    USER_GROUP_ID,
    MASTER_RIGHT_NAME,
)
from cmdb.models.user_model import CmdbUser
from cmdb.errors.manager.groups_manager import (
    GroupsManagerInsertError,
    GroupsManagerGetError,
    GroupsManagerIterationError,
    GroupsManagerUpdateError,
    GroupsManagerDeleteError,
)
from cmdb.errors.manager.users_manager import (
    UsersManagerAdminMemberError,
    UsersManagerGetError,
    UsersManagerUpdateError,
    UsersManagerDeleteError,
)
from cmdb.interface.rest_api.routes.user_management_routes.cmdb_groups.groups_constants import (
    GROUP_ADMIN_MEMBER_MSG,
    GROUP_CREATED_NOT_READABLE_MSG,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/groups'

ADMIN_USER_PUBLIC_ID: int = CmdbUser.ADMIN_PUBLIC_ID
ADMIN_GROUP_PUBLIC_ID: int = ADMIN_GROUP_ID
USER_GROUP_PUBLIC_ID: int = USER_GROUP_ID

GROUP_ID_FOR_CREATE: int = 9851
GROUP_ID_FOR_GET: int = 9852
GROUP_ID_FOR_UPDATE: int = 9853
GROUP_ID_FOR_DELETE_NONE: int = 9854
GROUP_ID_FOR_DELETE_MOVE: int = 9855
GROUP_ID_FOR_DELETE_MOVE_TARGET: int = 9856
GROUP_ID_FOR_DELETE_MODE: int = 9857
MISMATCHED_PAYLOAD_GROUP_ID: int = 9858
GROUP_ID_FOR_RIGHTS_UPDATE: int = 9859
GROUP_ID_FOR_LIST_RIGHTS: int = 9861
# A member id the error-mapping tests hand the redistribution; no such user is stored
USER_ID_MOVE_ERROR: int = 98991
GUARD_USER_PUBLIC_ID: int = 9860
MISSING_GROUP_ID: int = 9899

ALL_GROUP_IDS: list[int] = [
    GROUP_ID_FOR_CREATE,
    GROUP_ID_FOR_GET,
    GROUP_ID_FOR_UPDATE,
    GROUP_ID_FOR_DELETE_NONE,
    GROUP_ID_FOR_DELETE_MOVE,
    GROUP_ID_FOR_DELETE_MOVE_TARGET,
    GROUP_ID_FOR_DELETE_MODE,
    MISMATCHED_PAYLOAD_GROUP_ID,
    GROUP_ID_FOR_RIGHTS_UPDATE,
    GROUP_ID_FOR_LIST_RIGHTS,
]

ORIGINAL_LABEL: str = 'Original'
UPDATED_LABEL: str = 'Updated'


def _group_payload(public_id: int, label: str = ORIGINAL_LABEL,
                   rights: list[str] | None = None) -> dict[str, Any]:
    """Builds a CmdbUserGroup payload acceptable to POST /groups/ and PUT /groups/<id>."""
    return {
        'public_id': public_id,
        'name': f'group-{public_id}',
        'label': label,
        'rights': rights if rights is not None else [],
    }


def _group_doc(public_id: int, label: str = ORIGINAL_LABEL,
               rights: list[str] | None = None) -> dict[str, Any]:
    """Builds a complete CmdbUserGroup doc for direct DB insertion (bypasses POST validation)."""
    return _group_payload(public_id, label, rights)


def _insert_admin_rights_group(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> None:
    """Inserts a CmdbUserGroup carrying the ``base.*`` wildcard right (mirrors the bootstrap admin group)."""
    database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)\
        .insert_one(_group_doc(public_id, rights=[MASTER_RIGHT_NAME]))


@pytest.fixture(scope='module', autouse=True)
def _cleanup_groups_after_module(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any leftover test groups after the module's tests have run."""
    yield
    database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)\
        .delete_many({'public_id': {'$in': ALL_GROUP_IDS}})


def _drop_group(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> None:
    """Removes a single CmdbUserGroup doc directly via the collection, for per-test cleanup."""
    database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name).delete_one({'public_id': public_id})


def _insert_group_doc(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> None:
    """Inserts a CmdbUserGroup doc directly via the collection, bypassing the POST route validation."""
    database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name).insert_one(_group_doc(public_id))


def _insert_user_in_group(
    database_manager: MongoDatabaseManager,
    database_name: str,
    user_public_id: int,
    group_public_id: int,
) -> None:
    """Inserts a CmdbUser doc carrying the given ``group_id``, bypassing the POST route."""
    database_manager.get_collection(CmdbUser.COLLECTION, database_name).insert_one({
        'public_id': user_public_id,
        'user_name': f'user-{user_public_id}',
        'active': True,
        'group_id': group_public_id,
        'registration_time': datetime.now(timezone.utc),
        'password': 'hashed-stub',
    })


def _drop_user(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> None:
    """Removes a single CmdbUser doc directly via the collection, for per-test cleanup."""
    database_manager.get_collection(CmdbUser.COLLECTION, database_name).delete_one({'public_id': public_id})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       CREATE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestPostGroup:
    """POST /groups/ creates a new CmdbUserGroup and the new doc is queryable afterwards."""

    def test_creates_new_group(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """A POST with a fresh payload returns 201 and the group is then retrievable via GET."""
        try:
            response = rest_api.post(f'{ROUTE_URL}/', json=_group_payload(GROUP_ID_FOR_CREATE))

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
            # `public_id` is server-owned: the payload's id is purged, so the route names the real one
            created_id = response.get_json()['result_id']
            follow_up = rest_api.get(f'{ROUTE_URL}/{created_id}')
            assert follow_up.status_code == HTTPStatus.OK
        finally:
            _drop_group(database_manager, database_name, GROUP_ID_FOR_CREATE)
            _drop_group(database_manager, database_name, created_id)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       READ                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetGroup:
    """GET /groups/<id> and GET /groups/ return the expected envelopes."""

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """Inserts one group directly via the DB before each test and removes it after."""
        _insert_group_doc(database_manager, database_name, GROUP_ID_FOR_GET)
        yield
        _drop_group(database_manager, database_name, GROUP_ID_FOR_GET)

    def test_get_single_returns_group(self, rest_api) -> None:
        """A GET /groups/<id> for a seeded group returns 200 and a parseable payload."""
        response = rest_api.get(f'{ROUTE_URL}/{GROUP_ID_FOR_GET}')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert body['result']['public_id'] == GROUP_ID_FOR_GET

    def test_get_single_missing_returns_404(self, rest_api) -> None:
        """A GET /groups/<id> for a missing id returns 404."""
        response = rest_api.get(f'{ROUTE_URL}/{MISSING_GROUP_ID}')

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_get_list_returns_results_envelope(self, rest_api) -> None:
        """A GET /groups/ returns a JSON envelope whose results length matches X-Total-Count."""
        response = rest_api.get(f'{ROUTE_URL}/')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert 'results' in body
        assert len(body['results']) == int(response.headers['X-Total-Count'])


class TestListRights:
    """GET /groups/ answers each group's rights in the shape and with the content of GET /groups/<id>."""

    LISTED_RIGHTS: list[str] = ['base.framework.type.view', 'base.framework.object.*']

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """Inserts one group holding two rights directly via the DB and removes it after."""
        database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name).insert_one(
            _group_doc(GROUP_ID_FOR_LIST_RIGHTS, rights=self.LISTED_RIGHTS))
        yield
        _drop_group(database_manager, database_name, GROUP_ID_FOR_LIST_RIGHTS)

    @staticmethod
    def _listed(rest_api, public_id: int) -> dict[str, Any]:
        """The group as the list answers it."""
        response = rest_api.get(f'{ROUTE_URL}/', query_string={'filter': f'{{"public_id": {public_id}}}'})
        assert response.status_code == HTTPStatus.OK

        return next(group for group in response.get_json()['results'] if group['public_id'] == public_id)

    def test_a_listed_group_carries_the_rights_of_its_single_read(self, rest_api) -> None:
        """Same rights, same full-dict shape, same order - the list used to answer an empty list."""
        listed: dict[str, Any] = self._listed(rest_api, GROUP_ID_FOR_LIST_RIGHTS)
        single: dict[str, Any] = rest_api.get(f'{ROUTE_URL}/{GROUP_ID_FOR_LIST_RIGHTS}').get_json()['result']

        assert sorted(right['name'] for right in listed['rights']) == sorted(self.LISTED_RIGHTS)
        assert listed['rights'] == single['rights']

    def test_the_admin_group_is_listed_with_the_master_right(self, rest_api) -> None:
        """The bootstrap admin group holds ``base.*`` in the list too."""
        listed: dict[str, Any] = self._listed(rest_api, ADMIN_GROUP_PUBLIC_ID)

        assert [right['name'] for right in listed['rights']] == [MASTER_RIGHT_NAME]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       UPDATE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestPutGroup:
    """PUT /groups/<id> writes the new payload over the existing CmdbUserGroup."""

    def test_update_persists_new_label(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """After PUT, GET reflects the updated label."""
        _insert_group_doc(database_manager, database_name, GROUP_ID_FOR_UPDATE)
        try:
            response = rest_api.put(
                f'{ROUTE_URL}/{GROUP_ID_FOR_UPDATE}',
                json=_group_payload(GROUP_ID_FOR_UPDATE, UPDATED_LABEL),
            )

            assert response.status_code == HTTPStatus.ACCEPTED
            follow_up = rest_api.get(f'{ROUTE_URL}/{GROUP_ID_FOR_UPDATE}')
            assert follow_up.get_json()['result']['label'] == UPDATED_LABEL
        finally:
            _drop_group(database_manager, database_name, GROUP_ID_FOR_UPDATE)

    def test_update_missing_returns_404(self, rest_api) -> None:
        """PUT against a non-existent group id returns 404."""
        response = rest_api.put(
            f'{ROUTE_URL}/{MISSING_GROUP_ID}',
            json=_group_payload(MISSING_GROUP_ID, UPDATED_LABEL),
        )

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_update_pins_public_id_to_the_url(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """A payload public_id different from the URL cannot rewrite the document's identity."""
        collection = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
        _insert_group_doc(database_manager, database_name, GROUP_ID_FOR_UPDATE)
        try:
            response = rest_api.put(
                f'{ROUTE_URL}/{GROUP_ID_FOR_UPDATE}',
                json=_group_payload(MISMATCHED_PAYLOAD_GROUP_ID, UPDATED_LABEL),
            )

            assert response.status_code == HTTPStatus.ACCEPTED
            # The document keeps its URL id and is updated in place ...
            assert collection.find_one({'public_id': GROUP_ID_FOR_UPDATE})['label'] == UPDATED_LABEL
            # ... and no shadow document is created under the payload's id.
            assert collection.find_one({'public_id': MISMATCHED_PAYLOAD_GROUP_ID}) is None
        finally:
            _drop_group(database_manager, database_name, GROUP_ID_FOR_UPDATE)
            _drop_group(database_manager, database_name, MISMATCHED_PAYLOAD_GROUP_ID)


class TestPutAdminGroupMasterRight:
    """PUT /groups/<admin id> may never drop the master right, but stays editable otherwise."""

    @pytest.fixture(name='groups_collection')
    def _restore_admin_group(self, database_manager: MongoDatabaseManager, database_name: str):
        """Yields the groups collection and restores the bootstrap admin group doc afterwards."""
        collection = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
        original = collection.find_one({'public_id': ADMIN_GROUP_PUBLIC_ID})
        assert original is not None
        yield collection
        collection.replace_one({'public_id': ADMIN_GROUP_PUBLIC_ID}, original)

    def test_admin_group_cannot_drop_master_right(self, rest_api, groups_collection) -> None:
        """A payload without ``base.*`` is refused with 400 and the stored right is untouched."""
        admin_group = groups_collection.find_one({'public_id': ADMIN_GROUP_PUBLIC_ID})

        response = rest_api.put(
            f'{ROUTE_URL}/{ADMIN_GROUP_PUBLIC_ID}',
            json={
                'public_id': ADMIN_GROUP_PUBLIC_ID,
                'name': admin_group['name'],
                'label': admin_group['label'],
                'rights': [],
            },
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert MASTER_RIGHT_NAME in groups_collection.find_one({'public_id': ADMIN_GROUP_PUBLIC_ID})['rights']

    def test_admin_group_label_stays_editable(self, rest_api, groups_collection) -> None:
        """A payload keeping ``base.*`` is accepted, so the rest of the admin group remains editable."""
        admin_group = groups_collection.find_one({'public_id': ADMIN_GROUP_PUBLIC_ID})

        response = rest_api.put(
            f'{ROUTE_URL}/{ADMIN_GROUP_PUBLIC_ID}',
            json={
                'public_id': ADMIN_GROUP_PUBLIC_ID,
                'name': admin_group['name'],
                'label': UPDATED_LABEL,
                'rights': [MASTER_RIGHT_NAME],
            },
        )

        assert response.status_code == HTTPStatus.ACCEPTED
        stored = groups_collection.find_one({'public_id': ADMIN_GROUP_PUBLIC_ID})
        assert stored['label'] == UPDATED_LABEL
        assert MASTER_RIGHT_NAME in stored['rights']

    def test_other_group_may_drop_all_rights(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """The guard is admin-group only: any other group may still have all its rights removed."""
        _insert_admin_rights_group(database_manager, database_name, GROUP_ID_FOR_RIGHTS_UPDATE)
        try:
            response = rest_api.put(
                f'{ROUTE_URL}/{GROUP_ID_FOR_RIGHTS_UPDATE}',
                json=_group_payload(GROUP_ID_FOR_RIGHTS_UPDATE, rights=[]),
            )

            assert response.status_code == HTTPStatus.ACCEPTED
            stored = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)\
                .find_one({'public_id': GROUP_ID_FOR_RIGHTS_UPDATE})
            assert stored['rights'] == []
        finally:
            _drop_group(database_manager, database_name, GROUP_ID_FOR_RIGHTS_UPDATE)


class TestUpdateResponseShape:
    """PUT / PATCH /groups/<id> answer the stored group in the shape every other group route answers."""

    # Submitted out of tree order and with a duplicate; the update stores and answers each once, in tree order
    SUBMITTED_RIGHTS: list[str] = ['base.framework.object.*', 'base.framework.type.view', 'base.framework.object.*']
    STORED_RIGHT_NAMES: set[str] = {'base.framework.object.*', 'base.framework.type.view'}

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """Inserts the group to update directly via the DB and removes it after."""
        _insert_group_doc(database_manager, database_name, GROUP_ID_FOR_UPDATE)
        yield
        _drop_group(database_manager, database_name, GROUP_ID_FOR_UPDATE)

    @pytest.mark.parametrize('method', ['put', 'patch'])
    def test_the_update_answers_what_a_following_get_answers(self, rest_api, method: str) -> None:
        """Same rights, same full-dict shape, same tree order - the update used to answer name strings."""
        response = getattr(rest_api, method)(
            f'{ROUTE_URL}/{GROUP_ID_FOR_UPDATE}',
            json=_group_payload(GROUP_ID_FOR_UPDATE, UPDATED_LABEL, rights=self.SUBMITTED_RIGHTS),
        )

        assert response.status_code == HTTPStatus.ACCEPTED
        answered: dict[str, Any] = response.get_json()['result']
        read: dict[str, Any] = rest_api.get(f'{ROUTE_URL}/{GROUP_ID_FOR_UPDATE}').get_json()['result']
        assert answered == read
        assert all(isinstance(right, dict) for right in answered['rights'])
        assert {right['name'] for right in answered['rights']} == self.STORED_RIGHT_NAMES
        assert answered['label'] == UPDATED_LABEL

    def test_the_stored_rights_stay_name_strings(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """Only the answer is in the read shape: the document keeps the names the answer's dicts carry."""
        response = rest_api.put(
            f'{ROUTE_URL}/{GROUP_ID_FOR_UPDATE}',
            json=_group_payload(GROUP_ID_FOR_UPDATE, rights=self.SUBMITTED_RIGHTS),
        )

        stored = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)\
            .find_one({'public_id': GROUP_ID_FOR_UPDATE})
        assert stored['rights'] == [right['name'] for right in response.get_json()['result']['rights']]

    def test_the_update_and_the_create_answer_one_shape(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """For the same rights the create and the update answer the same list."""
        created = rest_api.post(f'{ROUTE_URL}/', json=_group_payload(GROUP_ID_FOR_CREATE, rights=self.SUBMITTED_RIGHTS))
        try:
            updated = rest_api.put(
                f'{ROUTE_URL}/{GROUP_ID_FOR_UPDATE}',
                json=_group_payload(GROUP_ID_FOR_UPDATE, rights=self.SUBMITTED_RIGHTS),
            )

            assert created.status_code == HTTPStatus.CREATED
            assert updated.get_json()['result']['rights'] == created.get_json()['raw']['rights']
        finally:
            # The create draws its own public_id, so the row is removed by its (unique) name
            database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)\
                .delete_one({'name': f'group-{GROUP_ID_FOR_CREATE}'})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       DELETE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDeleteGroup:
    """DELETE /groups/<id> with the parametrized GroupDeleteMode matrix."""

    def test_delete_none_action_removes_group(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """``action=None`` (no query) deletes the group; a follow-up GET returns 404."""
        _insert_group_doc(database_manager, database_name, GROUP_ID_FOR_DELETE_NONE)
        try:
            response = rest_api.delete(f'{ROUTE_URL}/{GROUP_ID_FOR_DELETE_NONE}')

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
            follow_up = rest_api.get(f'{ROUTE_URL}/{GROUP_ID_FOR_DELETE_NONE}')
            assert follow_up.status_code == HTTPStatus.NOT_FOUND
        finally:
            _drop_group(database_manager, database_name, GROUP_ID_FOR_DELETE_NONE)

    def test_delete_move_without_group_id_returns_400(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """``action=MOVE`` without a ``group_id`` is rejected with 400 (the Tier A bug fix)."""
        _insert_group_doc(database_manager, database_name, GROUP_ID_FOR_DELETE_MOVE)
        try:
            response = rest_api.delete(
                f'{ROUTE_URL}/{GROUP_ID_FOR_DELETE_MOVE}',
                query_string={'action': GroupDeleteMode.MOVE.value},
            )

            assert response.status_code == HTTPStatus.BAD_REQUEST
        finally:
            _drop_group(database_manager, database_name, GROUP_ID_FOR_DELETE_MOVE)

    def test_delete_move_reassigns_users_to_target(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """``action=MOVE`` + valid ``group_id`` reassigns the users to the target group."""
        moved_user_id: int = GROUP_ID_FOR_DELETE_MOVE + 1000
        _insert_group_doc(database_manager, database_name, GROUP_ID_FOR_DELETE_MOVE)
        _insert_group_doc(database_manager, database_name, GROUP_ID_FOR_DELETE_MOVE_TARGET)
        _insert_user_in_group(database_manager, database_name, moved_user_id, GROUP_ID_FOR_DELETE_MOVE)
        try:
            response = rest_api.delete(
                f'{ROUTE_URL}/{GROUP_ID_FOR_DELETE_MOVE}',
                query_string={
                    'action': GroupDeleteMode.MOVE.value,
                    'group_id': GROUP_ID_FOR_DELETE_MOVE_TARGET,
                },
            )

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
            moved_user = database_manager.get_collection(CmdbUser.COLLECTION, database_name)\
                .find_one({'public_id': moved_user_id})
            assert moved_user is not None
            assert moved_user['group_id'] == GROUP_ID_FOR_DELETE_MOVE_TARGET
        finally:
            _drop_user(database_manager, database_name, moved_user_id)
            _drop_group(database_manager, database_name, GROUP_ID_FOR_DELETE_MOVE_TARGET)
            _drop_group(database_manager, database_name, GROUP_ID_FOR_DELETE_MOVE)

    def test_delete_mode_with_admin_in_group_is_rejected(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """``action=DELETE`` is refused when the bootstrap admin user is a member of the deleted group."""
        users_collection = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
        original_admin = users_collection.find_one({'public_id': ADMIN_USER_PUBLIC_ID})
        assert original_admin is not None
        original_group_id = original_admin['group_id']

        _insert_admin_rights_group(database_manager, database_name, GROUP_ID_FOR_DELETE_MODE)
        users_collection.update_one(
            {'public_id': ADMIN_USER_PUBLIC_ID},
            {'$set': {'group_id': GROUP_ID_FOR_DELETE_MODE}},
        )
        try:
            response = rest_api.delete(
                f'{ROUTE_URL}/{GROUP_ID_FOR_DELETE_MODE}',
                query_string={'action': GroupDeleteMode.DELETE.value},
            )

            # Admin-in-group is a business-rule rejection -> 400 (not a 500 server fault).
            assert response.status_code == HTTPStatus.BAD_REQUEST
            # The group still exists because the delete was refused.
            follow_up = rest_api.get(f'{ROUTE_URL}/{GROUP_ID_FOR_DELETE_MODE}')
            assert follow_up.status_code == HTTPStatus.OK
        finally:
            users_collection.update_one(
                {'public_id': ADMIN_USER_PUBLIC_ID},
                {'$set': {'group_id': original_group_id}},
            )
            _drop_group(database_manager, database_name, GROUP_ID_FOR_DELETE_MODE)

    def test_delete_protected_group_is_rejected_without_touching_members(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """Deleting a protected bootstrap group is refused with 400, leaving its members untouched."""
        # Seed a throwaway member of the protected user group; the move target (admin group) exists.
        _insert_user_in_group(database_manager, database_name, GUARD_USER_PUBLIC_ID, USER_GROUP_PUBLIC_ID)
        try:
            response = rest_api.delete(
                f'{ROUTE_URL}/{USER_GROUP_PUBLIC_ID}',
                query_string={'action': GroupDeleteMode.MOVE.value, 'group_id': ADMIN_GROUP_PUBLIC_ID},
            )

            assert response.status_code == HTTPStatus.BAD_REQUEST
            # The protected group still exists ...
            assert rest_api.get(f'{ROUTE_URL}/{USER_GROUP_PUBLIC_ID}').status_code == HTTPStatus.OK
            # ... and the member was NOT moved (no side effects on a rejected delete).
            guard_user = database_manager.get_collection(CmdbUser.COLLECTION, database_name)\
                .find_one({'public_id': GUARD_USER_PUBLIC_ID})
            assert guard_user['group_id'] == USER_GROUP_PUBLIC_ID
        finally:
            _drop_user(database_manager, database_name, GUARD_USER_PUBLIC_ID)

    def test_delete_missing_group_returns_404(self, rest_api) -> None:
        """DELETE against a missing group id returns 404 regardless of action."""
        response = rest_api.delete(f'{ROUTE_URL}/{MISSING_GROUP_ID}')

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_delete_move_target_missing_returns_404(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """``action=MOVE`` to a non-existent target group returns 404."""
        _insert_group_doc(database_manager, database_name, GROUP_ID_FOR_DELETE_MOVE)
        try:
            response = rest_api.delete(
                f'{ROUTE_URL}/{GROUP_ID_FOR_DELETE_MOVE}',
                query_string={
                    'action': GroupDeleteMode.MOVE.value,
                    'group_id': MISSING_GROUP_ID,
                },
            )

            assert response.status_code == HTTPStatus.NOT_FOUND
        finally:
            _drop_group(database_manager, database_name, GROUP_ID_FOR_DELETE_MOVE)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   ERROR MAPPING                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def _raiser(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


def _patch_get_group(monkeypatch, ids, *, raises: Exception | None = None, returns: Any = None) -> None:
    """
    Selectively patches GroupsManager.get_group for the given target ids only

    The lookup for any other id (notably the request user's own group, resolved by the ACL
    ``protect`` check) delegates to the real method, so authorization still succeeds and only the
    route's target lookup is stubbed / raised.
    """
    id_set = {ids} if isinstance(ids, int) else set(ids)
    original = GroupsManager.get_group

    def _selective(self, public_id):
        if public_id in id_set:
            if raises is not None:
                raise raises
            return returns
        return original(self, public_id)

    monkeypatch.setattr(GroupsManager, 'get_group', _selective)


def _patch_group_exists(monkeypatch, public_id: int, *, raises: Exception | None = None) -> None:
    """
    Selectively patches GroupsManager.group_exists for the given target id only

    The target answers True (or raises); any other id delegates to the real check, as in
    ``_patch_get_group``.
    """
    original = GroupsManager.group_exists

    def _selective(self, requested_id):
        if requested_id == public_id:
            if raises is not None:
                raise raises
            return True
        return original(self, requested_id)

    monkeypatch.setattr(GroupsManager, 'group_exists', _selective)


def _patch_group_snapshot(monkeypatch, public_id: int) -> None:
    """
    Makes the delete route's snapshot read find a stored document for a group only get_group was stubbed for

    Any other id delegates to the real read, as in `_patch_get_group`.
    """
    original = GroupsManager.get_item

    def _selective(self, requested_id, as_dict=False):
        if requested_id == public_id:
            return {'public_id': public_id, 'name': f'group-{public_id}', 'label': 'G', 'rights': []}
        return original(self, requested_id, as_dict=as_dict)

    monkeypatch.setattr(GroupsManager, 'get_item', _selective)


class TestErrorMapping:
    """Manager failures map to the documented HTTP statuses across the /groups routes."""

    def test_an_insert_error_that_is_no_duplicate_returns_500(self, rest_api, monkeypatch) -> None:
        """
        A GroupsManagerInsertError alone is no taken name: only a typed refusal in its chain is

        It used to be a 400, the same one a duplicate name answered - so an outage read as the caller's
        fault, and the caller learned nothing about the name.
        """
        monkeypatch.setattr(GroupsManager, 'insert_group', _raiser(GroupsManagerInsertError('boom')))

        assert rest_api.post(f'{ROUTE_URL}/',
                             json=_group_payload(GROUP_ID_FOR_CREATE)).status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_insert_created_retrieval_none_returns_500(self, rest_api, monkeypatch) -> None:
        """The insert worked but the read-back found nothing: the server lost its own write, not a 404."""
        monkeypatch.setattr(GroupsManager, 'insert_group', lambda *_a, **_k: 999)
        _patch_get_group(monkeypatch, 999, returns=None)

        response = rest_api.post(f'{ROUTE_URL}/', json=_group_payload(GROUP_ID_FOR_CREATE))

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert response.get_json()['message'] == GROUP_CREATED_NOT_READABLE_MSG

    def test_insert_created_retrieval_error_returns_500(self, rest_api, monkeypatch) -> None:
        """A get error while re-reading the created group surfaces as 500 (server-side)."""
        monkeypatch.setattr(GroupsManager, 'insert_group', lambda *_a, **_k: 999)
        _patch_get_group(monkeypatch, 999, raises=GroupsManagerGetError('boom'))

        assert rest_api.post(f'{ROUTE_URL}/',
                             json=_group_payload(GROUP_ID_FOR_CREATE)).status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_insert_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on create surfaces as 500."""
        monkeypatch.setattr(GroupsManager, 'insert_group', _raiser(RuntimeError('boom')))

        assert rest_api.post(f'{ROUTE_URL}/',
                             json=_group_payload(GROUP_ID_FOR_CREATE)).status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_list_iteration_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A GroupsManagerIterationError on list surfaces as 400."""
        monkeypatch.setattr(GroupsManager, 'iterate', _raiser(GroupsManagerIterationError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.BAD_REQUEST

    def test_list_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on list surfaces as 500."""
        monkeypatch.setattr(GroupsManager, 'iterate', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_get_single_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A GroupsManagerGetError on get-single surfaces as 400."""
        _patch_get_group(monkeypatch, GROUP_ID_FOR_GET, raises=GroupsManagerGetError('boom'))

        assert rest_api.get(f'{ROUTE_URL}/{GROUP_ID_FOR_GET}').status_code == HTTPStatus.BAD_REQUEST

    def test_get_single_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on get-single surfaces as 500."""
        _patch_get_group(monkeypatch, GROUP_ID_FOR_GET, raises=RuntimeError('boom'))

        assert rest_api.get(f'{ROUTE_URL}/{GROUP_ID_FOR_GET}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_update_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A GroupsManagerGetError while checking that the group to update exists surfaces as 400."""
        _patch_group_exists(monkeypatch, GROUP_ID_FOR_UPDATE, raises=GroupsManagerGetError('boom'))

        assert rest_api.put(f'{ROUTE_URL}/{GROUP_ID_FOR_UPDATE}',
                            json=_group_payload(GROUP_ID_FOR_UPDATE)).status_code == HTTPStatus.BAD_REQUEST

    def test_an_update_error_that_is_no_duplicate_returns_500(self, rest_api, monkeypatch) -> None:
        """A GroupsManagerUpdateError alone says nothing about the request - a 500, not the old 400."""
        _patch_group_exists(monkeypatch, GROUP_ID_FOR_UPDATE)
        monkeypatch.setattr(GroupsManager, 'update_group', _raiser(GroupsManagerUpdateError('boom')))

        assert rest_api.put(f'{ROUTE_URL}/{GROUP_ID_FOR_UPDATE}',
                            json=_group_payload(GROUP_ID_FOR_UPDATE)).status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_update_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on update surfaces as 500."""
        _patch_group_exists(monkeypatch, GROUP_ID_FOR_UPDATE)
        monkeypatch.setattr(GroupsManager, 'update_group', _raiser(RuntimeError('boom')))

        assert rest_api.put(f'{ROUTE_URL}/{GROUP_ID_FOR_UPDATE}',
                            json=_group_payload(GROUP_ID_FOR_UPDATE)).status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_delete_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A GroupsManagerGetError while loading the group to delete surfaces as 400."""
        _patch_get_group(monkeypatch, GROUP_ID_FOR_DELETE_NONE, raises=GroupsManagerGetError('boom'))

        assert rest_api.delete(f'{ROUTE_URL}/{GROUP_ID_FOR_DELETE_NONE}').status_code == HTTPStatus.BAD_REQUEST

    def test_delete_error_returns_500(self, rest_api, monkeypatch) -> None:
        """A GroupsManagerDeleteError is the server failing its own write: 500, after the undo."""
        _patch_get_group(monkeypatch, GROUP_ID_FOR_DELETE_NONE, returns=object())
        _patch_group_snapshot(monkeypatch, GROUP_ID_FOR_DELETE_NONE)
        monkeypatch.setattr(GroupsManager, 'is_protected_group', lambda *_a, **_k: False)
        monkeypatch.setattr(GroupsManager, 'delete_group', _raiser(GroupsManagerDeleteError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{GROUP_ID_FOR_DELETE_NONE}').status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_delete_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on delete surfaces as 500."""
        _patch_get_group(monkeypatch, GROUP_ID_FOR_DELETE_NONE, returns=object())
        _patch_group_snapshot(monkeypatch, GROUP_ID_FOR_DELETE_NONE)
        monkeypatch.setattr(GroupsManager, 'is_protected_group', lambda *_a, **_k: False)
        monkeypatch.setattr(GroupsManager, 'delete_group', _raiser(RuntimeError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{GROUP_ID_FOR_DELETE_NONE}').status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_delete_move_user_update_error_returns_500(self, rest_api, monkeypatch) -> None:
        """A UsersManagerUpdateError while moving members is a failed write: 500, after the undo."""
        _patch_get_group(monkeypatch, {GROUP_ID_FOR_DELETE_MOVE, GROUP_ID_FOR_DELETE_MOVE_TARGET}, returns=object())
        _patch_group_snapshot(monkeypatch, GROUP_ID_FOR_DELETE_MOVE)
        monkeypatch.setattr(GroupsManager, 'is_protected_group', lambda *_a, **_k: False)
        monkeypatch.setattr(UsersManager, 'get_group_member_ids', lambda *_a, **_k: [USER_ID_MOVE_ERROR])
        monkeypatch.setattr(UsersManager, 'handle_users_on_group_delete',
                            _raiser(UsersManagerUpdateError('boom')))

        assert rest_api.delete(
            f'{ROUTE_URL}/{GROUP_ID_FOR_DELETE_MOVE}',
            query_string={'action': GroupDeleteMode.MOVE.value, 'group_id': GROUP_ID_FOR_DELETE_MOVE_TARGET},
        ).status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_delete_user_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A UsersManagerGetError while resolving members surfaces as 400."""
        _patch_get_group(monkeypatch, GROUP_ID_FOR_DELETE_MODE, returns=object())
        _patch_group_snapshot(monkeypatch, GROUP_ID_FOR_DELETE_MODE)
        monkeypatch.setattr(GroupsManager, 'is_protected_group', lambda *_a, **_k: False)
        monkeypatch.setattr(UsersManager, 'get_group_member_ids', _raiser(UsersManagerGetError('boom')))

        assert rest_api.delete(
            f'{ROUTE_URL}/{GROUP_ID_FOR_DELETE_MODE}',
            query_string={'action': GroupDeleteMode.DELETE.value},
        ).status_code == HTTPStatus.BAD_REQUEST

    def test_a_group_gone_before_its_snapshot_is_a_404(self, rest_api, monkeypatch) -> None:
        """Found by the first read, gone by the snapshot read: nothing to delete and nothing written."""
        _patch_get_group(monkeypatch, GROUP_ID_FOR_DELETE_NONE, returns=object())
        monkeypatch.setattr(GroupsManager, 'is_protected_group', lambda *_a, **_k: False)
        original = GroupsManager.get_item
        monkeypatch.setattr(GroupsManager, 'get_item', lambda self, public_id, as_dict=False: None
                            if public_id == GROUP_ID_FOR_DELETE_NONE else original(self, public_id, as_dict=as_dict))
        monkeypatch.setattr(GroupsManager, 'delete_group', _raiser(AssertionError('must not delete')))

        assert rest_api.delete(f'{ROUTE_URL}/{GROUP_ID_FOR_DELETE_NONE}').status_code == HTTPStatus.NOT_FOUND

    def test_delete_admin_backstop_maps_to_400(self, rest_api, monkeypatch) -> None:
        """The manager's admin refusal (the pre-check's backstop) is the business rule: 400, its own message."""
        _patch_get_group(monkeypatch, GROUP_ID_FOR_DELETE_MODE, returns=object())
        _patch_group_snapshot(monkeypatch, GROUP_ID_FOR_DELETE_MODE)
        monkeypatch.setattr(GroupsManager, 'is_protected_group', lambda *_a, **_k: False)
        monkeypatch.setattr(UsersManager, 'get_group_member_ids', lambda *_a, **_k: [USER_ID_MOVE_ERROR])
        monkeypatch.setattr(UsersManager, 'handle_users_on_group_delete',
                            _raiser(UsersManagerAdminMemberError('admin')))

        response = rest_api.delete(f'{ROUTE_URL}/{GROUP_ID_FOR_DELETE_MODE}',
                                   query_string={'action': GroupDeleteMode.DELETE.value})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == GROUP_ADMIN_MEMBER_MSG

    def test_a_failed_member_delete_is_a_500_not_the_admin_message(self, rest_api, monkeypatch) -> None:
        """An outage while deleting members is not the admin refusal: 500, and the admin is not named."""
        _patch_get_group(monkeypatch, GROUP_ID_FOR_DELETE_MODE, returns=object())
        _patch_group_snapshot(monkeypatch, GROUP_ID_FOR_DELETE_MODE)
        monkeypatch.setattr(GroupsManager, 'is_protected_group', lambda *_a, **_k: False)
        monkeypatch.setattr(UsersManager, 'get_group_member_ids', lambda *_a, **_k: [USER_ID_MOVE_ERROR])
        monkeypatch.setattr(UsersManager, 'handle_users_on_group_delete',
                            _raiser(UsersManagerDeleteError('db down')))

        response = rest_api.delete(f'{ROUTE_URL}/{GROUP_ID_FOR_DELETE_MODE}',
                                   query_string={'action': GroupDeleteMode.DELETE.value})

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert 'admin' not in response.get_json()['message']
