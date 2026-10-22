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
Functional coverage for what the routes of the small narrowed managers answer when their manager fails

The user-settings, docapi-template, extendable-option, logs and section-template managers catch only the failures
their calls raise. A database failure - the ``BaseManager*Error`` of the call - is still the manager's own error and
the route's 400. A programming error is not dressed up as that 400: it reaches the route's generic tail and answers
500. Each case patches the delegate the route's read goes through, on the manager class the route builds
"""
from http import HTTPStatus
from typing import Any
from unittest.mock import patch

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.docapi_templates_manager import DocapiTemplatesManager
from cmdb.manager.extendable_options_manager import ExtendableOptionsManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.manager.logs_manager import LogsManager
from cmdb.manager.section_templates_manager import SectionTemplatesManager
from cmdb.manager.user_settings_manager import UserSettingsManager
from cmdb.manager.types_manager import TypesManager
from cmdb.framework.docapi.docapi_template.docapi_template import DocapiTemplate
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.settings_model import CmdbUserSetting
from cmdb.models.type_model import SectionType
from cmdb.errors.manager import BaseManagerGetError, BaseManagerIterationError
from cmdb.errors.manager.types_manager import TypesManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

ADMIN_USER_ID: int = 1
SETTING_RESOURCE: str = 'small-manager-error-status'
TEMPLATE_ID: int = 97201
DOCAPI_TEMPLATE_ID: int = 97202
TEMPLATE_NAME: str = 'small-manager-error-status'
GLOBAL_TEMPLATE_NAME: str = 'small-manager-error-status-global'
GLOBAL_TEMPLATE_ID: int = 97203
BUG: str = 'a programming error'
DB_FAILURE: str = 'the read failed'

# route, the manager and delegate under it, and the typed failure that delegate raises
CASES: list[tuple[str, type, str, type[Exception]]] = [
    (f'/users/{ADMIN_USER_ID}/settings/{SETTING_RESOURCE}', UserSettingsManager, 'get_one_by', BaseManagerGetError),
    (f'/users/{ADMIN_USER_ID}/settings/', UserSettingsManager, 'find', BaseManagerGetError),
    ('/docapi/template/?minimal=true', DocapiTemplatesManager, 'aggregate_within_time_limit',
     BaseManagerIterationError),
    ('/extendable_options/', ExtendableOptionsManager, 'iterate_query', BaseManagerIterationError),
    ('/logs/object/deleted', LogsManager, 'iterate_query', BaseManagerIterationError),
    ('/section_templates/', SectionTemplatesManager, 'iterate_query', BaseManagerIterationError),
    (f'/section_templates/{TEMPLATE_ID}', SectionTemplatesManager, 'get_one', BaseManagerGetError),
    (f'/section_templates/{GLOBAL_TEMPLATE_ID}/count', TypesManager, 'get_types_by', TypesManagerGetError),
]
CASE_IDS: list[str] = [
    'user-setting', 'user-settings', 'docapi-minimal', 'extendable-options', 'logs',
    'section-templates', 'section-template', 'section-template-count',
]


def _section_template(public_id: int, name: str, is_global: bool) -> dict[str, Any]:
    """A stored, non-predefined section template"""
    return {'public_id': public_id, 'name': name, 'label': name, 'type': SectionType.SECTION.value,
            'fields': [], 'is_global': is_global, 'predefined': False}


@pytest.fixture(autouse=True)
def _licensed(monkeypatch) -> None:
    """The document-generator routes are licence-gated; every feature is licensed here"""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, _feature: True)


@pytest.fixture(autouse=True)
def _seeded(database_manager: MongoDatabaseManager, database_name: str):
    """A user setting of the admin, a docapi template and two section templates; removed again afterwards"""
    settings = database_manager.get_collection(CmdbUserSetting.COLLECTION, database_name)
    templates = database_manager.get_collection(CmdbSectionTemplate.COLLECTION, database_name)
    docapi_templates = database_manager.get_collection(DocapiTemplate.COLLECTION, database_name)

    def _purge() -> None:
        settings.delete_many({'user_id': ADMIN_USER_ID, 'resource': SETTING_RESOURCE})
        templates.delete_many({'public_id': {'$in': [TEMPLATE_ID, GLOBAL_TEMPLATE_ID]}})
        docapi_templates.delete_many({'public_id': DOCAPI_TEMPLATE_ID})

    _purge()
    settings.insert_one({'resource': SETTING_RESOURCE, 'user_id': ADMIN_USER_ID, 'payloads': [],
                         'setting_type': 'GLOBAL'})
    templates.insert_many([
        _section_template(TEMPLATE_ID, TEMPLATE_NAME, False),
        _section_template(GLOBAL_TEMPLATE_ID, GLOBAL_TEMPLATE_NAME, True),
    ])
    docapi_templates.insert_one({'public_id': DOCAPI_TEMPLATE_ID, 'name': TEMPLATE_NAME})

    yield

    _purge()


@pytest.mark.parametrize('url, manager, delegate, typed', CASES, ids=CASE_IDS)
def test_the_route_answers_without_a_failure(rest_api, url: str, manager: type, delegate: str,
                                             typed: type[Exception]) -> None:
    """The control: each route answers 200 as it stands"""
    del manager, delegate, typed

    assert rest_api.get(url).status_code == HTTPStatus.OK


@pytest.mark.parametrize('url, manager, delegate, typed', CASES, ids=CASE_IDS)
def test_a_programming_error_answers_500(rest_api, url: str, manager: type, delegate: str,
                                         typed: type[Exception]) -> None:
    """Not the 400 a failed read gets: the bug is the server's, and is not dressed up as a database failure"""
    del typed

    with patch.object(manager, delegate, side_effect=TypeError(BUG)):
        response = rest_api.get(url)

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR


@pytest.mark.parametrize('url, manager, delegate, typed', CASES, ids=CASE_IDS)
def test_a_database_failure_still_answers_400(rest_api, url: str, manager: type, delegate: str,
                                              typed: type[Exception]) -> None:
    """The call's own failure is the manager's error, which the route answers 400 with its message"""
    with patch.object(manager, delegate, side_effect=typed(DB_FAILURE)):
        response = rest_api.get(url)

    body: dict[str, Any] = response.get_json()

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert body['message']


# -------------------------------------------------------------------------------------------------------------------- #
#                                  the reads ahead of a create, and the SOA option labels                              #
# -------------------------------------------------------------------------------------------------------------------- #
CREATED_NAME: str = 'small-manager-error-status-created'
SOA_REPORT_URL: str = '/isms/reports/soa'

# what is posted and the manager whose counter read precedes the insert; nothing may be created when it fails
CREATE_CASES: list[tuple[str, dict[str, Any], type]] = [
    ('docapi', {'name': CREATED_NAME, 'active': True}, DocapiTemplatesManager),
    ('section-template', {'name': CREATED_NAME, 'label': CREATED_NAME, 'type': SectionType.SECTION.value,
                          'is_global': 'false', 'predefined': 'false', 'fields': '[]'}, SectionTemplatesManager),
]
CREATE_IDS: list[str] = [case[0] for case in CREATE_CASES]
DOCAPI_KIND: str = CREATE_IDS[0]


def _post_create(rest_api, kind: str, body: dict[str, Any]) -> Any:
    """POSTs the create of the given kind in the shape its route reads"""
    if kind == DOCAPI_KIND:
        return rest_api.post('/docapi/template/', json=body)

    return rest_api.post('/section_templates/', query_string=body)


@pytest.fixture(name='created_purged')
def fixture_created_purged(database_manager: MongoDatabaseManager, database_name: str):
    """Removes anything a create in these tests wrote, by its name"""
    collections = [database_manager.get_collection(collection, database_name)
                   for collection in (DocapiTemplate.COLLECTION, CmdbSectionTemplate.COLLECTION)]

    def _purge() -> None:
        for collection in collections:
            collection.delete_many({'name': CREATED_NAME})

    _purge()
    yield collections
    _purge()


@pytest.mark.parametrize('kind, body, manager', CREATE_CASES, ids=CREATE_IDS)
def test_a_failed_id_reservation_answers_400_and_creates_nothing(rest_api, created_purged, kind: str,
                                                                  body: dict[str, Any], manager: type) -> None:
    """The counter read ahead of the insert is the manager's typed failure: a 400, and no template is written"""
    with patch.object(manager, 'get_next_public_id', side_effect=BaseManagerGetError(DB_FAILURE)):
        response = _post_create(rest_api, kind, body)

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert all(collection.count_documents({'name': CREATED_NAME}) == 0 for collection in created_purged)


@pytest.mark.parametrize('kind, body, manager', CREATE_CASES, ids=CREATE_IDS)
def test_a_programming_error_in_the_id_reservation_answers_500(rest_api, created_purged, kind: str,
                                                                body: dict[str, Any], manager: type) -> None:
    """A bug under the counter read is the server's: a 500"""
    del created_purged

    with patch.object(manager, 'get_next_public_id', side_effect=TypeError(BUG)):
        response = _post_create(rest_api, kind, body)

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR


def test_a_failed_option_label_read_answers_the_soa_report_400(rest_api) -> None:
    """The SOA report's option-label read failing is the report's 400, like its control-measure read"""
    with patch.object(ExtendableOptionsManager, 'find', side_effect=BaseManagerGetError(DB_FAILURE)):
        response = rest_api.get(SOA_REPORT_URL)

    assert response.status_code == HTTPStatus.BAD_REQUEST


def test_a_programming_error_in_the_option_label_read_answers_the_soa_report_500(rest_api) -> None:
    """A bug under the option-label read is the server's: a 500"""
    with patch.object(ExtendableOptionsManager, 'find', side_effect=TypeError(BUG)):
        response = rest_api.get(SOA_REPORT_URL)

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
