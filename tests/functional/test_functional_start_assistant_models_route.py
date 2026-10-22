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
Functional tests for the best-practice model routes of the start assistant

``GET /start_assistant/models`` and ``GET /start_assistant/models/<model_id>``, through the real app. The catalogue the
routes read is patched to one loaded by the real catalogue code from ``tmp_path`` (``tests.utils.best_practice_model_
fixture``); the bundled folder itself is read once too. Pinned: both rights are asked (403 naming the one missing),
the cards come in card order with the counts, chips and licence answer computed from the file - ``applicable`` false
on an installation without IPAM, true with it -, the details carry the tree with every reference target named, and an
unknown id is a 404. Applying (``POST``) runs only for the administrator account and only into a reset system: it
writes into a scratch target the managers are routed to, imports the model, records ``best_practice_model`` and then
refuses a second model; an unlicensed model and an installation that is not empty are refused with nothing recorded
"""
from dataclasses import asdict
from datetime import datetime, timezone
from http import HTTPStatus
from pathlib import Path
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_services.database_services_constants import UpdaterSetting
from cmdb.manager import SettingsManager
from cmdb.manager.manager_provider_model import ManagerProvider
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID
from cmdb.models.type_model import CmdbType
from cmdb.interface.rest_api.routes.cmdb_license.license_guard import (
    FEATURE_NOT_LICENSED_MESSAGE,
    LICENSE_FEATURE_LABELS,
)
from cmdb.interface.rest_api.routes.configuration_transfer_routes.configuration_transfer_route_constants import (
    ADMIN_ONLY_MESSAGE,
)
from cmdb.framework.configuration_transfer import BestPracticeCatalogue, load_catalogue
from cmdb.framework.configuration_transfer.best_practice_preview import PreviewCounts
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.group_model.group_constants import USER_GROUP_ID
from cmdb.models.user_model import CmdbUser
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.interface.rest_api.routes.start_assistant_routes import start_assistant_routes
from cmdb.interface.rest_api.routes.start_assistant_routes.start_assistant_constants import (
    MODEL_NOT_FOUND_MESSAGE,
    START_ASSISTANT_RIGHTS,
    START_ASSISTANT_SETTINGS_SECTION,
    BestPracticeApplyKey,
    BestPracticeModelKey,
    StartAssistantDecision,
    StartAssistantKey,
    StartAssistantOfferKey,
)
from tests.utils.best_practice_model_fixture import (
    COMPANY_NAME,
    COMPANY_TYPE_ID,
    CUSTOMER_TYPE_ID,
    MODEL_DB_VERSION,
    SUPERNET_TYPE_ID,
    CUSTOMER_NAME,
    EMPLOYER_FIELD,
    model_document,
    model_meta,
    write_model_pair,
)
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

MODELS_URL: str = '/start_assistant/models'
RIGHT_REFUSAL: str = 'User has not the required right {right}'
FIRST_ID: str = 'clients'
SECOND_ID: str = 'infrastructure'
UNKNOWN_ID: str = 'no_such_model'
TYPE_ONLY_GROUP_ID: int = 88761
TYPE_ONLY_USER_ID: int = 88771
DEFAULT_USER_ID: int = 88772
IPAM: str = LicenseFeature.IPAM.value
TARGET_SUFFIX: str = '-best-practice-target'
SECOND_ADMIN_ID: int = 88773
EXISTING_TYPE_ID: int = 88781
OFFER_URL: str = '/start_assistant/offer'

# The detail tree's keys are the preview dataclasses' field names
NAME, TYPES, SECTIONS, FIELDS, TARGETS = 'name', 'types', 'sections', 'fields', 'targets'


def _ids(response: Any) -> list[str]:
    """The model ids of a card list, in its order"""
    return [card[BestPracticeModelKey.MODEL_ID.value] for card in response.get_json()]


@pytest.fixture(name='catalogue')
def fixture_catalogue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> BestPracticeCatalogue:
    """Two models - the infrastructure one needs IPAM and comes second by its order"""
    write_model_pair(tmp_path, SECOND_ID, meta=model_meta(title='Infrastructure', order=20))
    write_model_pair(tmp_path, FIRST_ID, document=model_document(with_supernet=False),
                     meta=model_meta(title='Clients', order=10))
    catalogue: BestPracticeCatalogue = load_catalogue(tmp_path)
    monkeypatch.setattr(start_assistant_routes, 'get_best_practice_catalogue', lambda: catalogue)

    return catalogue


def _licensed(monkeypatch: pytest.MonkeyPatch, licensed: bool) -> None:
    """Every feature licensed, or none"""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, _feature: licensed)


@pytest.fixture(name='users')
def fixture_users(database_manager: MongoDatabaseManager, database_name: str):
    """A member of a group holding type.add only, and a member of the seeded user group"""
    groups = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)

    def _purge() -> None:
        groups.delete_many({'public_id': TYPE_ONLY_GROUP_ID})
        users.delete_many({'public_id': {'$in': [TYPE_ONLY_USER_ID, DEFAULT_USER_ID]}})

    def _user(user_id: int, group_id: int) -> CmdbUser:
        users.insert_one({'public_id': user_id, 'user_name': f'best-practice-{user_id}', 'active': True,
                          'group_id': group_id, 'registration_time': datetime.now(timezone.utc)})

        return CmdbUser(public_id=user_id, user_name=f'best-practice-{user_id}', active=True, group_id=group_id)

    _purge()
    groups.insert_one({'public_id': TYPE_ONLY_GROUP_ID, 'name': 'best-practice-type', 'label': 'T',
                       'rights': [START_ASSISTANT_RIGHTS[0]]})
    yield {'type-only': _user(TYPE_ONLY_USER_ID, TYPE_ONLY_GROUP_ID), 'default': _user(DEFAULT_USER_ID, USER_GROUP_ID)}
    _purge()


class TestTheCards:
    """GET /start_assistant/models"""

    @pytest.mark.usefixtures('catalogue')
    def test_the_cards_come_in_card_order(self, rest_api, monkeypatch) -> None:
        """By the description files' order, not by name or file"""
        _licensed(monkeypatch, False)

        response = rest_api.get(MODELS_URL)

        assert response.status_code == HTTPStatus.OK
        assert _ids(response) == [FIRST_ID, SECOND_ID]

    @pytest.mark.usefixtures('catalogue')
    def test_without_ipam_the_licensed_model_is_not_applicable(self, rest_api, monkeypatch) -> None:
        """The infrastructure model needs IPAM; the clients model needs nothing"""
        _licensed(monkeypatch, False)

        cards = {card[BestPracticeModelKey.MODEL_ID.value]: card for card in rest_api.get(MODELS_URL).get_json()}

        assert (cards[SECOND_ID][BestPracticeModelKey.REQUIRED_FEATURES.value],
                cards[SECOND_ID][BestPracticeModelKey.MISSING_FEATURES.value],
                cards[SECOND_ID][BestPracticeModelKey.APPLICABLE.value]) == ([IPAM], [IPAM], False)
        assert cards[FIRST_ID][BestPracticeModelKey.APPLICABLE.value] is True

    @pytest.mark.usefixtures('catalogue')
    def test_with_ipam_every_model_is_applicable(self, rest_api, monkeypatch) -> None:
        """Required, not missing"""
        _licensed(monkeypatch, True)

        cards = rest_api.get(MODELS_URL).get_json()

        assert all(card[BestPracticeModelKey.APPLICABLE.value] for card in cards)
        assert not any(card[BestPracticeModelKey.MISSING_FEATURES.value] for card in cards)

    @pytest.mark.usefixtures('catalogue')
    def test_a_card_carries_the_computed_counts_and_chips(self, rest_api, monkeypatch) -> None:
        """From the model file, never the description file"""
        _licensed(monkeypatch, False)

        card = rest_api.get(MODELS_URL).get_json()[1]

        expected_counts = PreviewCounts(categories=1, types=3, fields=4, relations=1)

        assert card[BestPracticeModelKey.COUNTS.value] == asdict(expected_counts)
        assert card[BestPracticeModelKey.CATEGORY_LABELS.value] == ['Contact']
        assert card[BestPracticeModelKey.TITLE.value] == 'Infrastructure'

    def test_an_empty_catalogue_lists_nothing(self, rest_api, monkeypatch) -> None:
        """No error, no card"""
        monkeypatch.setattr(start_assistant_routes, 'get_best_practice_catalogue',
                            lambda: BestPracticeCatalogue([]))

        response = rest_api.get(MODELS_URL)

        assert (response.status_code, response.get_json()) == (HTTPStatus.OK, [])

    def test_the_bundled_catalogue_is_served(self, rest_api) -> None:
        """The real folder, unpatched: whatever it holds loads into cards"""
        response = rest_api.get(MODELS_URL)

        assert response.status_code == HTTPStatus.OK
        assert isinstance(response.get_json(), list)

    @pytest.mark.usefixtures('catalogue')
    @pytest.mark.parametrize('who, missing', [('default', START_ASSISTANT_RIGHTS[0]),
                                              ('type-only', START_ASSISTANT_RIGHTS[1])])
    def test_both_rights_are_needed(self, rest_api, users, who: str, missing: str) -> None:
        """403 naming the first right the caller lacks"""
        response = rest_api.get(MODELS_URL, user=users[who])

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == RIGHT_REFUSAL.format(right=missing)


@pytest.mark.usefixtures('catalogue')
class TestTheDetails:
    """GET /start_assistant/models/<model_id>"""

    def test_the_details_carry_the_tree(self, rest_api, monkeypatch) -> None:
        """The customer's employer field names the company it targets"""
        _licensed(monkeypatch, False)

        response = rest_api.get(f'{MODELS_URL}/{SECOND_ID}')
        details = response.get_json()
        types = details[BestPracticeModelKey.CATEGORIES.value][0][TYPES]
        customer = next(type_ for type_ in types if type_[NAME] == CUSTOMER_NAME)
        employer = next(field for field in customer[SECTIONS][0][FIELDS] if field[NAME] == EMPLOYER_FIELD)

        assert response.status_code == HTTPStatus.OK
        assert details[BestPracticeModelKey.MODEL_ID.value] == SECOND_ID
        assert details[BestPracticeModelKey.APPLICABLE.value] is False
        assert [target[NAME] for target in employer[TARGETS]] == [COMPANY_NAME]

    @pytest.mark.parametrize('model_id', [UNKNOWN_ID, 'Infrastructure', 'infrastructure.json'],
                             ids=['unknown', 'other-case', 'file-name'])
    def test_an_unknown_id_is_a_404(self, rest_api, model_id: str) -> None:
        """Only an offered model's exact id"""
        response = rest_api.get(f'{MODELS_URL}/{model_id}')

        assert response.status_code == HTTPStatus.NOT_FOUND
        assert response.get_json()['message'] == MODEL_NOT_FOUND_MESSAGE.format(model_id=model_id)

    @pytest.mark.parametrize('who, missing', [('default', START_ASSISTANT_RIGHTS[0]),
                                              ('type-only', START_ASSISTANT_RIGHTS[1])])
    def test_both_rights_are_needed(self, rest_api, users, who: str, missing: str) -> None:
        """403 before the model is looked up - an unknown id too"""
        response = rest_api.get(f'{MODELS_URL}/{UNKNOWN_ID}', user=users[who])

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == RIGHT_REFUSAL.format(right=missing)



# -------------------------------------------------------------------------------------------------------------------- #
#                                                  applying a model                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.fixture(name='target')
def fixture_target(database_manager: MongoDatabaseManager, database_name: str,
                   monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """
    A reset target recording the model file's version; the managers routed to it

    The caller is still read from the session database, but the rights check reads its group through the same routing,
    so the groups are copied over - a group is no blocker of an import
    """
    name: str = f'{database_name}{TARGET_SUFFIX}'
    client = database_manager.connector.client
    client.drop_database(name)
    groups: list[dict[str, Any]] = list(client[database_name][CmdbUserGroup.COLLECTION].find())
    client[name][CmdbUserGroup.COLLECTION].insert_many(groups)
    SettingsManager(database_manager, name).write(UpdaterSetting.SECTION.value,
                                                  {UpdaterSetting.VERSION.value: MODEL_DB_VERSION})
    monkeypatch.setattr(ManagerProvider, 'tenant_database', staticmethod(lambda request_user: name))

    yield client[name]

    client.drop_database(name)


@pytest.fixture(name='second_admin')
def fixture_second_admin(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[CmdbUser]:
    """An active member of the admin group who is not the administrator account"""
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    users.delete_many({'public_id': SECOND_ADMIN_ID})
    users.insert_one({'public_id': SECOND_ADMIN_ID, 'user_name': 'best-practice-admin', 'active': True,
                      'group_id': ADMIN_GROUP_ID, 'registration_time': datetime.now(timezone.utc)})

    yield CmdbUser(public_id=SECOND_ADMIN_ID, user_name='best-practice-admin', active=True, group_id=ADMIN_GROUP_ID)

    users.delete_many({'public_id': SECOND_ADMIN_ID})


def _type_ids(target: Any) -> list[int]:
    """The types the target holds"""
    return sorted(document['public_id'] for document in target[CmdbType.COLLECTION].find({}, {'public_id': 1}))


def _decision(target: Any) -> dict[str, Any] | None:
    """The start assistant's recorded decision in the target"""
    return target[SettingsManager.COLLECTION].find_one({'_id': START_ASSISTANT_SETTINGS_SECTION})


@pytest.mark.usefixtures('catalogue')
class TestApplyingAModel:
    """POST /start_assistant/models/<model_id>"""

    def test_the_administrator_applies_a_model(self, rest_api, target) -> None:
        """Imported into the target, best_practice_model recorded with the model's id"""
        response = rest_api.post(f'{MODELS_URL}/{FIRST_ID}')
        answer = response.get_json()

        assert response.status_code == HTTPStatus.OK
        assert answer[BestPracticeApplyKey.MODEL_ID.value] == FIRST_ID
        assert answer[BestPracticeApplyKey.IMPORTED.value]['types'] == 2
        assert _type_ids(target) == [COMPANY_TYPE_ID, CUSTOMER_TYPE_ID]
        stored = _decision(target)
        assert (stored[StartAssistantKey.DECISION.value], stored[StartAssistantKey.MODEL.value],
                stored[StartAssistantKey.DECIDED_BY.value]) == (
                    StartAssistantDecision.BEST_PRACTICE_MODEL.value, FIRST_ID, 1)

    def test_a_second_model_is_refused_and_the_offer_asks_for_a_reset(self, rest_api, target) -> None:
        """One model per installation: the system is no longer reset"""
        rest_api.post(f'{MODELS_URL}/{FIRST_ID}')

        response = rest_api.post(f'{MODELS_URL}/{FIRST_ID}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _type_ids(target) == [COMPANY_TYPE_ID, CUSTOMER_TYPE_ID]
        assert rest_api.get(OFFER_URL).get_json()[StartAssistantOfferKey.RESET_REQUIRED.value] is True

    def test_a_licensed_model_is_applied_on_a_licensed_installation(self, rest_api, monkeypatch, target) -> None:
        """The Supernet comes along"""
        _licensed(monkeypatch, True)

        assert rest_api.post(f'{MODELS_URL}/{SECOND_ID}').status_code == HTTPStatus.OK
        assert SUPERNET_TYPE_ID in _type_ids(target)

    def test_an_unlicensed_model_is_refused_with_nothing_written(self, rest_api, monkeypatch, target) -> None:
        """The licence gates' own 403; never applied in part"""
        _licensed(monkeypatch, False)

        response = rest_api.post(f'{MODELS_URL}/{SECOND_ID}')

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == FEATURE_NOT_LICENSED_MESSAGE.format(
            feature=LICENSE_FEATURE_LABELS[LicenseFeature.IPAM])
        assert not _type_ids(target)
        assert _decision(target) is None

    def test_an_installation_that_is_not_empty_is_refused(self, rest_api, target) -> None:
        """A type already stored: 400 naming it, nothing imported, no decision recorded"""
        target[CmdbType.COLLECTION].insert_one(make_type_doc(EXISTING_TYPE_ID, 'already-there'))

        response = rest_api.post(f'{MODELS_URL}/{FIRST_ID}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert CmdbType.COLLECTION in response.get_json()['message']
        assert _type_ids(target) == [EXISTING_TYPE_ID]
        assert _decision(target) is None

    @pytest.mark.usefixtures('target')
    def test_an_unknown_id_is_a_404(self, rest_api) -> None:
        """Nothing imported"""
        response = rest_api.post(f'{MODELS_URL}/{UNKNOWN_ID}')

        assert response.status_code == HTTPStatus.NOT_FOUND
        assert response.get_json()['message'] == MODEL_NOT_FOUND_MESSAGE.format(model_id=UNKNOWN_ID)

    def test_only_the_administrator_account_applies(self, rest_api, target, second_admin) -> None:
        """Another member of the admin group is refused before the model is looked up"""
        response = rest_api.post(f'{MODELS_URL}/{UNKNOWN_ID}', user=second_admin)

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == ADMIN_ONLY_MESSAGE
        assert not _type_ids(target)
