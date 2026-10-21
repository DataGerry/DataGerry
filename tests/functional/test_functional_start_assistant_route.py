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
Functional tests for the ``/start_assistant`` routes

The "installation is empty" gate reads the shared session database, so the counts are patched to 0 where a test needs
an empty installation; the decision section is removed before and after every test. Pinned:
  - POST asks for both rights (403 naming the missing one), refuses a body that is not ``{"decision": <known>}`` and
    an installation a configuration import would refuse (400, reset first); it stores the decision with the caller
    and the time, and a later decision replaces an earlier one while the installation is still empty
  - GET /start_assistant/offer answers {show, available, reset_required}: show + available on an empty installation
    before a decision, show false once one is recorded while it stays empty, reset_required once anything blocks a
    configuration import, all false without the rights - and without the rights nothing is read. "Empty" is the
    import's own precondition, pinned against a real scratch database: a lone webhook already requires a reset
  - the older DataGerry Assistant does not read the decision: /special/intro answers as before
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import SettingsManager
from cmdb.manager.base_manager import BaseManager
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.group_model.group_constants import USER_GROUP_ID
from cmdb.models.user_model import CmdbUser
from cmdb.manager.manager_provider_model import ManagerProvider
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.settings_model.cmdb_user_setting import CmdbUserSetting
from cmdb.models.webhook_model.cmdb_webhook_model import CmdbWebhook
from cmdb.framework.docapi.docapi_template.docapi_template import DocapiTemplate
from cmdb.interface.rest_api.routes.framework_routes.special_constants import ASSISTANT_SETTINGS_SECTION
from cmdb.interface.rest_api.routes.start_assistant_routes.start_assistant_constants import (
    DECISION_PAYLOAD_INVALID_MESSAGE,
    DECISION_READ_FAILED_MESSAGE,
    RESET_REQUIRED_MESSAGE,
    START_ASSISTANT_RIGHTS,
    START_ASSISTANT_SETTINGS_SECTION,
    StartAssistantDecision,
)
from cmdb.errors.database import DocumentGetError
# -------------------------------------------------------------------------------------------------------------------- #

DECISION_URL: str = '/start_assistant/decision'
OFFER_URL: str = '/start_assistant/offer'
INTRO_URL: str = '/special/intro'
RIGHT_REFUSAL: str = 'User has not the required right {right}'
ADMIN_USER_ID: int = 1
EMPTY: str = StartAssistantDecision.EMPTY_DATA_MODEL.value
EARLIER: datetime = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

TYPE_ONLY_GROUP_ID: int = 88741
BOTH_GROUP_ID: int = 88742
TYPE_ONLY_USER_ID: int = 88751
BOTH_USER_ID: int = 88752
DEFAULT_USER_ID: int = 88753


def _empty(monkeypatch: pytest.MonkeyPatch, count: int = 0) -> None:
    """
    Makes every 'installation is empty' check see ``count`` documents in every collection

    The start assistant asks the import's precondition (cross-collection counts); the older assistant's /intro counts
    its own three collections
    """
    monkeypatch.setattr(BaseManager, 'count_from_other_collection', lambda _self, *_a, **_k: count)
    monkeypatch.setattr(BaseManager, 'count_documents', lambda _self, *_a, **_k: count)


def _message(response: Any) -> str:
    """The refusal message of an error response"""
    return response.get_json()['message']


@pytest.fixture(name='settings', autouse=True)
def fixture_settings(database_manager: MongoDatabaseManager, database_name: str):
    """The decision section (and the old assistant's marker) removed before and after every test"""
    settings = database_manager.get_collection(SettingsManager.COLLECTION, database_name)
    sections: list[str] = [START_ASSISTANT_SETTINGS_SECTION, ASSISTANT_SETTINGS_SECTION]
    settings.delete_many({'_id': {'$in': sections}})
    yield settings
    settings.delete_many({'_id': {'$in': sections}})


def _insert_user(database_manager: MongoDatabaseManager, database_name: str, user_id: int,
                 group_id: int) -> CmdbUser:
    """Stores an active user in ``group_id`` and answers the model the test client sends as"""
    database_manager.get_collection(CmdbUser.COLLECTION, database_name).insert_one({
        'public_id': user_id, 'user_name': f'start-assistant-{user_id}', 'active': True, 'group_id': group_id,
        'registration_time': datetime.now(timezone.utc),
    })

    return CmdbUser(public_id=user_id, user_name=f'start-assistant-{user_id}', active=True, group_id=group_id)


@pytest.fixture(name='users')
def fixture_users(database_manager: MongoDatabaseManager, database_name: str):
    """A group holding type.add only, one holding both rights, and a member of the seeded user group"""
    groups = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)

    def _purge() -> None:
        groups.delete_many({'public_id': {'$in': [TYPE_ONLY_GROUP_ID, BOTH_GROUP_ID]}})
        users.delete_many({'public_id': {'$in': [TYPE_ONLY_USER_ID, BOTH_USER_ID, DEFAULT_USER_ID]}})

    _purge()
    groups.insert_many([
        {'public_id': TYPE_ONLY_GROUP_ID, 'name': 'start-assistant-type', 'label': 'T',
         'rights': [START_ASSISTANT_RIGHTS[0]]},
        {'public_id': BOTH_GROUP_ID, 'name': 'start-assistant-both', 'label': 'B',
         'rights': list(START_ASSISTANT_RIGHTS)},
    ])
    yield {
        'type-only': _insert_user(database_manager, database_name, TYPE_ONLY_USER_ID, TYPE_ONLY_GROUP_ID),
        'both': _insert_user(database_manager, database_name, BOTH_USER_ID, BOTH_GROUP_ID),
        'default': _insert_user(database_manager, database_name, DEFAULT_USER_ID, USER_GROUP_ID),
    }
    _purge()


class TestRecordTheDecision:
    """POST /start_assistant/decision"""

    def test_an_empty_installation_records_it_with_the_caller(self, rest_api, monkeypatch, settings, users) -> None:
        """200, the answer and the stored section carry the decision, the caller and the time"""
        _empty(monkeypatch)
        before: datetime = datetime.now(timezone.utc)

        response = rest_api.post(DECISION_URL, json={'decision': EMPTY}, user=users['both'])

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['decision'] == EMPTY
        assert response.get_json()['decided_by'] == BOTH_USER_ID
        stored: dict[str, Any] = settings.find_one({'_id': START_ASSISTANT_SETTINGS_SECTION})
        assert (stored['decision'], stored['decided_by']) == (EMPTY, BOTH_USER_ID)
        assert stored['decided_at'].replace(tzinfo=timezone.utc) >= before.replace(microsecond=0)
        assert rest_api.get(OFFER_URL, user=users['both']).get_json()['show'] is False

    def test_a_later_decision_replaces_the_earlier_one(self, rest_api, monkeypatch, settings, users) -> None:
        """No reset needed while the installation is still empty: the newer caller and time win"""
        _empty(monkeypatch)
        settings.insert_one({'_id': START_ASSISTANT_SETTINGS_SECTION, 'decision': EMPTY, 'decided_by': ADMIN_USER_ID,
                             'decided_at': EARLIER})

        response = rest_api.post(DECISION_URL, json={'decision': EMPTY}, user=users['both'])

        assert response.status_code == HTTPStatus.OK
        stored: dict[str, Any] = settings.find_one({'_id': START_ASSISTANT_SETTINGS_SECTION})
        assert stored['decided_by'] == BOTH_USER_ID
        assert stored['decided_at'].replace(tzinfo=timezone.utc) > EARLIER
        assert settings.count_documents({'_id': START_ASSISTANT_SETTINGS_SECTION}) == 1

    def test_a_non_empty_installation_is_a_400_and_nothing_is_stored(self, rest_api, monkeypatch, settings) -> None:
        """Categories, types or objects exist"""
        _empty(monkeypatch, count=1)

        response = rest_api.post(DECISION_URL, json={'decision': EMPTY})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _message(response) == RESET_REQUIRED_MESSAGE
        assert settings.find_one({'_id': START_ASSISTANT_SETTINGS_SECTION}) is None

    @pytest.mark.parametrize('body', [{}, {'decision': EMPTY, 'decided_by': 1}, [EMPTY]])
    def test_a_body_that_is_not_the_one_key_is_a_400(self, rest_api, monkeypatch, body: Any) -> None:
        """Exactly {'decision': ...}"""
        _empty(monkeypatch)

        response = rest_api.post(DECISION_URL, json=body)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _message(response) == DECISION_PAYLOAD_INVALID_MESSAGE

    def test_an_unknown_decision_is_a_400_and_nothing_is_stored(self, rest_api, monkeypatch, settings) -> None:
        """Only the StartAssistantDecision values"""
        _empty(monkeypatch)

        response = rest_api.post(DECISION_URL, json={'decision': 'import'})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert "Unknown decision 'import'" in _message(response)
        assert settings.find_one({'_id': START_ASSISTANT_SETTINGS_SECTION}) is None

    @pytest.mark.parametrize('who, missing', [('default', START_ASSISTANT_RIGHTS[0]),
                                              ('type-only', START_ASSISTANT_RIGHTS[1])])
    def test_both_rights_are_needed(self, rest_api, monkeypatch, settings, users, who: str, missing: str) -> None:
        """403 naming the first right the caller lacks; nothing stored"""
        _empty(monkeypatch)

        response = rest_api.post(DECISION_URL, json={'decision': EMPTY}, user=users[who])

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert _message(response) == RIGHT_REFUSAL.format(right=missing)
        assert settings.find_one({'_id': START_ASSISTANT_SETTINGS_SECTION}) is None


def test_the_older_assistant_does_not_read_the_decision(rest_api, monkeypatch) -> None:
    """The two assistants are independent: /special/intro still offers the old one on an empty installation"""
    _empty(monkeypatch)
    rest_api.post(DECISION_URL, json={'decision': EMPTY})

    assert rest_api.get(INTRO_URL).get_json() is True


class TestTheOffer:
    """GET /start_assistant/offer"""

    def test_never_run_on_an_empty_installation_shows_it(self, rest_api, monkeypatch, users) -> None:
        """Both flags true"""
        _empty(monkeypatch)

        response = rest_api.get(OFFER_URL, user=users['both'])

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == {'show': True, 'available': True, 'reset_required': False}

    def test_after_the_empty_data_model_it_stays_available_but_does_not_open_itself(
            self, rest_api, monkeypatch, users) -> None:
        """A decision on a still-empty installation"""
        _empty(monkeypatch)
        rest_api.post(DECISION_URL, json={'decision': EMPTY}, user=users['both'])

        assert rest_api.get(OFFER_URL, user=users['both']).get_json() == {
            'show': False, 'available': True, 'reset_required': False,
        }

    def test_once_data_exists_a_reset_is_required(self, rest_api, monkeypatch, users) -> None:
        """Something blocks an import: not shown, not available, reset first"""
        _empty(monkeypatch, count=1)

        assert rest_api.get(OFFER_URL, user=users['both']).get_json() == {
            'show': False, 'available': False, 'reset_required': True,
        }

    @pytest.mark.parametrize('who', ['default', 'type-only'])
    def test_without_both_rights_it_is_neither_and_nothing_is_read(self, rest_api, monkeypatch, users,
                                                                  who: str) -> None:
        """The counts and the decision are never read for such a caller"""
        def _no_read(*_args: Any, **_kwargs: Any) -> None:
            raise AssertionError('read for a caller without the rights')

        monkeypatch.setattr(BaseManager, 'count_from_other_collection', _no_read)
        monkeypatch.setattr(SettingsManager, 'get_section', _no_read)

        response = rest_api.get(OFFER_URL, user=users[who])

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == {'show': False, 'available': False, 'reset_required': False}

    def test_a_failed_read_is_a_400(self, rest_api, monkeypatch, users) -> None:
        """The decision read failing on an empty installation"""
        def _failing(*_args: Any, **_kwargs: Any) -> None:
            raise DocumentGetError('settings gone')

        _empty(monkeypatch)
        monkeypatch.setattr(SettingsManager, 'get_section', _failing)

        response = rest_api.get(OFFER_URL, user=users['both'])

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _message(response) == DECISION_READ_FAILED_MESSAGE


# -------------------------------------------------------------------------------------------------------------------- #
#                              "empty" is the configuration import's own precondition                                  #
# -------------------------------------------------------------------------------------------------------------------- #
SCRATCH_SUFFIX: str = '-start-assistant-scratch'
ROOT_LOCATION_ID: int = 1
LEFT_OVER_ID: int = 88771


@pytest.fixture(name='scratch')
def fixture_scratch(database_manager: MongoDatabaseManager, database_name: str,
                    monkeypatch: pytest.MonkeyPatch):
    """
    An empty scratch installation the managers are routed to - only the root location, which a reset keeps

    The groups are copied over: the rights check reads the caller's group through the same routing
    """
    scratch: str = f'{database_name}{SCRATCH_SUFFIX}'
    client = database_manager.connector.client
    client.drop_database(scratch)
    client[scratch][CmdbLocation.COLLECTION].insert_one({'public_id': ROOT_LOCATION_ID})
    client[scratch][CmdbUserGroup.COLLECTION].insert_many(
        list(client[database_name][CmdbUserGroup.COLLECTION].find({})),
    )
    monkeypatch.setattr(ManagerProvider, 'tenant_database', staticmethod(lambda request_user: scratch))

    yield client[scratch]

    client.drop_database(scratch)


@pytest.mark.parametrize('collection, leftover', [
    (CmdbWebhook.COLLECTION, {'name': 'left over'}),
    (DocapiTemplate.COLLECTION, {'name': 'left over'}),
    (CmdbSectionTemplate.COLLECTION, {'name': 'user-made', 'predefined': False}),
    (CmdbMetaLog.COLLECTION, {'object_id': LEFT_OVER_ID}),
])
def test_a_leftover_the_import_refuses_requires_a_reset(rest_api, scratch, collection: str,
                                                        leftover: dict[str, Any]) -> None:
    """Not only categories, types and objects: whatever blocks an import blocks the assistant, and the POST too"""
    assert rest_api.get(OFFER_URL).get_json() == {'show': True, 'available': True, 'reset_required': False}

    scratch[collection].insert_one({'public_id': LEFT_OVER_ID, **leftover})

    assert rest_api.get(OFFER_URL).get_json() == {'show': False, 'available': False, 'reset_required': True}
    response = rest_api.post(DECISION_URL, json={'decision': EMPTY})
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert _message(response) == RESET_REQUIRED_MESSAGE


@pytest.mark.parametrize('collection, kept', [
    (CmdbSectionTemplate.COLLECTION, {'name': 'predefined', 'predefined': True}),
    (CmdbUserSetting.COLLECTION, {'identifier': 'table-settings'}),
    (CmdbLocation.COLLECTION, None),
])
def test_what_the_import_accepts_keeps_it_available(rest_api, scratch, collection: str,
                                                    kept: dict[str, Any] | None) -> None:
    """Predefined templates, user settings and the root location do not block an import - nor the assistant"""
    if kept is not None:
        scratch[collection].insert_one({'public_id': LEFT_OVER_ID, **kept})

    assert rest_api.get(OFFER_URL).get_json() == {'show': True, 'available': True, 'reset_required': False}
    assert rest_api.post(DECISION_URL, json={'decision': EMPTY}).status_code == HTTPStatus.OK
