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
Functional tests of POST /configuration_transfer/reset through the real REST app

The refusals run against the session database - each is answered before anything is read or deleted, and the
seeded sentinel type proves it. The successful reset runs against a scratch database: the managers' tenant
resolver is pointed there, so the real reset empties that database and never the session's.

What is pinned: no token is a 401; any user but public_id 1 is a 403 - a member of the admin group too, and before
the body is looked at; a missing, wrong or non-object confirmation is a 400; the administrator's confirmed reset
answers the deleted count per collection, empties every target, keeps what the reset keeps and removes the
assistant marker, and a second reset answers zeros
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.base_manager import BaseManager
from cmdb.manager.manager_provider_model import ManagerProvider
from cmdb.framework.configuration_transfer import RESET_TARGETS, find_non_empty_targets
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.location_model.location_constants import RootLocationDefault
from cmdb.manager.system_manager.settings_manager import SettingsManager
from cmdb.interface.blueprints.api_blueprint_constants import BODY_NOT_AN_OBJECT_MESSAGE
from cmdb.interface.rest_api.routes.framework_routes.special_constants import ASSISTANT_SETTINGS_SECTION
from cmdb.interface.rest_api.routes.start_assistant_routes.start_assistant_constants import (
    START_ASSISTANT_SETTINGS_SECTION,
    StartAssistantDecision,
    StartAssistantKey,
)
from cmdb.interface.rest_api.routes.configuration_transfer_routes.configuration_transfer_route_constants import (
    ADMIN_ONLY_MESSAGE,
    RESET_CONFIRMATION,
    ResetRequestKey,
    ResetResponseKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

RESET_URL: str = '/configuration_transfer/reset'
CONFIRMED: dict[str, str] = {ResetRequestKey.CONFIRM.value: RESET_CONFIRMATION}

ADMIN_GROUP_ID: int = 1
SECOND_ADMIN_ID: int = 93980
SECOND_ADMIN_NAME: str = 'reset-second-admin'
SENTINEL_TYPE_ID: int = 93981
SCRATCH_SUFFIX: str = '-reset-route'
PUBLIC_ID_KEY: str = 'public_id'
LEFT_OVER_ID: int = 2


@pytest.fixture(name='sentinel_type')
def fixture_sentinel_type(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[None]:
    """A type in the session database that a refused reset must leave in place"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    types.delete_many({PUBLIC_ID_KEY: SENTINEL_TYPE_ID})
    types.insert_one({PUBLIC_ID_KEY: SENTINEL_TYPE_ID, 'name': 'reset-sentinel'})

    yield

    assert types.count_documents({PUBLIC_ID_KEY: SENTINEL_TYPE_ID}) == 1
    types.delete_many({PUBLIC_ID_KEY: SENTINEL_TYPE_ID})


@pytest.fixture(name='second_admin')
def fixture_second_admin(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[CmdbUser]:
    """An active member of the admin group who is not the administrator account"""
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    users.delete_many({PUBLIC_ID_KEY: SECOND_ADMIN_ID})
    users.insert_one({PUBLIC_ID_KEY: SECOND_ADMIN_ID, 'user_name': SECOND_ADMIN_NAME, 'active': True,
                      'group_id': ADMIN_GROUP_ID, 'registration_time': datetime.now(timezone.utc)})

    yield CmdbUser(public_id=SECOND_ADMIN_ID, user_name=SECOND_ADMIN_NAME, active=True, group_id=ADMIN_GROUP_ID)

    users.delete_many({PUBLIC_ID_KEY: SECOND_ADMIN_ID})


@pytest.fixture(name='scratch')
def fixture_scratch(database_manager: MongoDatabaseManager, database_name: str,
                    monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """A scratch database the managers are routed to: one left-over per target, the root location, the marker"""
    scratch: str = f'{database_name}{SCRATCH_SUFFIX}'
    client = database_manager.connector.client
    client.drop_database(scratch)

    for target in RESET_TARGETS:
        client[scratch][target.collection].insert_one({PUBLIC_ID_KEY: LEFT_OVER_ID, **_matching(target.criteria)})

    client[scratch][CmdbLocation.COLLECTION].insert_one({PUBLIC_ID_KEY: RootLocationDefault.PUBLIC_ID})
    SettingsManager(database_manager, scratch).write(ASSISTANT_SETTINGS_SECTION, {'claimed_by': 1})
    SettingsManager(database_manager, scratch).write(START_ASSISTANT_SETTINGS_SECTION, {
        StartAssistantKey.DECISION.value: StartAssistantDecision.EMPTY_DATA_MODEL.value,
    })
    monkeypatch.setattr(ManagerProvider, 'tenant_database', staticmethod(lambda request_user: scratch))

    yield scratch

    client.drop_database(scratch)


def _matching(criteria: dict[str, Any]) -> dict[str, Any]:
    """The fields a document needs for an equality criteria to match it (operator criteria need none here)"""
    document: dict[str, Any] = {}

    for path, value in criteria.items():
        if isinstance(value, dict):
            continue

        *parents, leaf = path.split('.')
        level: dict[str, Any] = document

        for parent in parents:
            level = level.setdefault(parent, {})

        level[leaf] = value

    return document


def _message(response: Any) -> str:
    """The error message of a refusal"""
    return response.get_json()['message']

# -------------------------------------------------------------------------------------------------------------------- #
#                                                       refusals                                                       #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.usefixtures('sentinel_type')
class TestRefusals:
    """Every refusal is answered before anything is deleted"""

    def test_no_token_is_a_401(self, rest_api) -> None:
        """No Authorization header -> 401"""
        response = rest_api.post(RESET_URL, json=CONFIRMED, environ_overrides={'HTTP_AUTHORIZATION': ''})

        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_a_member_of_the_admin_group_is_a_403(self, rest_api, second_admin: CmdbUser) -> None:
        """Full rights are not enough - only the administrator account"""
        response = rest_api.post(RESET_URL, json=CONFIRMED, user=second_admin)

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert _message(response) == ADMIN_ONLY_MESSAGE

    def test_the_403_comes_before_the_body_is_read(self, rest_api, second_admin: CmdbUser) -> None:
        """A non-administrator with a broken body still gets the 403, not the body's 400"""
        response = rest_api.post(RESET_URL, json=['not', 'an', 'object'], user=second_admin)

        assert response.status_code == HTTPStatus.FORBIDDEN

    @pytest.mark.parametrize('body', [
        {},
        {ResetRequestKey.CONFIRM.value: 'reset'},
        {ResetRequestKey.CONFIRM.value: ''},
        {ResetRequestKey.CONFIRM.value: True},
    ])
    def test_a_missing_or_wrong_confirmation_is_a_400(self, rest_api, body: dict[str, Any]) -> None:
        """The value must be exactly the confirmation word; the message names the key"""
        response = rest_api.post(RESET_URL, json=body)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert ResetRequestKey.CONFIRM.value in _message(response)

    def test_a_body_that_is_no_object_is_a_400(self, rest_api) -> None:
        """A JSON list is answered with the shared not-an-object message"""
        response = rest_api.post(RESET_URL, json=[RESET_CONFIRMATION])

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert BODY_NOT_AN_OBJECT_MESSAGE in _message(response)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                     the reset                                                        #
# -------------------------------------------------------------------------------------------------------------------- #

class TestTheReset:
    """The administrator's confirmed reset, routed to a scratch database"""

    @pytest.mark.usefixtures('scratch')
    def test_answers_the_deleted_count_per_collection_in_list_order(self, rest_api) -> None:
        """One left-over per target -> 1 per collection, in the order the reset cleared them"""
        response = rest_api.post(RESET_URL, json=CONFIRMED)

        assert response.status_code == HTTPStatus.OK
        assert list(response.get_json()[ResetResponseKey.DELETED.value].items()) == [
            (target.collection, 1) for target in RESET_TARGETS
        ]

    def test_empties_every_target_and_keeps_the_root(self, rest_api, database_manager: MongoDatabaseManager,
                                                     scratch: str) -> None:
        """Nothing left over afterwards; the root location is still there"""
        rest_api.post(RESET_URL, json=CONFIRMED)

        assert not find_non_empty_targets(BaseManager(CmdbType.COLLECTION, database_manager, scratch))
        assert database_manager.get_collection(CmdbLocation.COLLECTION, scratch).count_documents(
            {PUBLIC_ID_KEY: RootLocationDefault.PUBLIC_ID}) == 1

    def test_removes_the_assistant_marker(self, rest_api, database_manager: MongoDatabaseManager,
                                          scratch: str) -> None:
        """The assistant may run again on the reset system"""
        rest_api.post(RESET_URL, json=CONFIRMED)

        assert SettingsManager(database_manager, scratch).get_section(ASSISTANT_SETTINGS_SECTION) is None

    def test_removes_the_start_assistant_decision(self, rest_api, database_manager: MongoDatabaseManager,
                                                  scratch: str) -> None:
        """The start assistant's decision starts over: its settings section is gone"""
        rest_api.post(RESET_URL, json=CONFIRMED)

        assert SettingsManager(database_manager, scratch).get_section(START_ASSISTANT_SETTINGS_SECTION) is None

    @pytest.mark.usefixtures('scratch')
    def test_a_second_reset_answers_zeros(self, rest_api) -> None:
        """Re-run safe: nothing left to delete, still a 200"""
        rest_api.post(RESET_URL, json=CONFIRMED)
        response = rest_api.post(RESET_URL, json=CONFIRMED)

        assert response.status_code == HTTPStatus.OK
        assert set(response.get_json()[ResetResponseKey.DELETED.value].values()) == {0}

    def test_a_failing_step_is_a_500_that_says_to_run_it_again(self, rest_api, database_manager: MongoDatabaseManager,
                                                                scratch: str, monkeypatch: pytest.MonkeyPatch) -> None:
        """A step that fails answers 500 naming the remedy; the marker stays for a run that did not finish"""
        def _failing(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError('database gone')

        monkeypatch.setattr(BaseManager, 'delete_many_from_other_collection', _failing)

        response = rest_api.post(RESET_URL, json=CONFIRMED)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert 'run the reset again' in _message(response)
        assert SettingsManager(database_manager, scratch).get_section(ASSISTANT_SETTINGS_SECTION) is not None
        assert SettingsManager(database_manager, scratch).get_section(START_ASSISTANT_SETTINGS_SECTION) is not None
