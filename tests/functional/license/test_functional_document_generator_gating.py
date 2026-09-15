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
Functional tests for document-generator feature-gating over HTTP

With no license active (the free default) every document-generator surface is blocked with HTTP 403
- reads included (decision D5: the whole feature locks, an exception to the reads-stay-open rule).
When the document_generator feature is licensed the routes are reachable again, and in local (cloud)
mode the guard is bypassed entirely. The licensed/bypass paths assert the route is no longer 403
(the guard let it through); they do not exercise the handlers' own success bodies
"""
from http import HTTPStatus

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.license_manager.active_license_manager import ActiveLicenseManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #

# Document-generator surfaces (template list lives on the docs blueprint at /docs, the rest on /docapi)
TEMPLATE_LIST_URL: str = '/docs/template'
TEMPLATE_SINGLE_URL: str = '/docapi/template/1'
# The create route is registered WITH the trailing slash (the form the frontend calls)
TEMPLATE_CREATE_URL: str = '/docapi/template/'
RENDER_URL: str = '/docapi/template/1/render/1'
CHATGPT_MESSAGE_URL: str = '/chatgpt/message'


@pytest.fixture(autouse=True)
def _no_active_license(database_manager: MongoDatabaseManager, database_name: str):
    """Guarantees the free (unlicensed) default by clearing the active-license store around each test"""
    database_manager.get_collection(ActiveLicenseManager.COLLECTION, database_name).delete_many({})
    yield
    database_manager.get_collection(ActiveLicenseManager.COLLECTION, database_name).delete_many({})


# -------------------------------------------------------------------------------------------------------------------- #
#                                          blocked without a license                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_create_template_blocked_without_license(rest_api) -> None:
    """Creating a template is blocked with 403 when document_generator is not licensed"""
    assert rest_api.post(TEMPLATE_CREATE_URL, json={}).status_code == HTTPStatus.FORBIDDEN


def test_template_list_blocked_without_license(rest_api) -> None:
    """The template list (a read) is blocked with 403 - the whole feature locks (D5)"""
    assert rest_api.get(TEMPLATE_LIST_URL).status_code == HTTPStatus.FORBIDDEN


def test_single_template_read_blocked_without_license(rest_api) -> None:
    """Reading a single template is blocked with 403 when document_generator is not licensed"""
    assert rest_api.get(TEMPLATE_SINGLE_URL).status_code == HTTPStatus.FORBIDDEN


def test_render_blocked_without_license(rest_api) -> None:
    """Rendering a template to PDF (a gated 'use') is blocked with 403 without a license"""
    assert rest_api.get(RENDER_URL).status_code == HTTPStatus.FORBIDDEN


def test_chatgpt_assist_blocked_without_license(rest_api) -> None:
    """The AI document assist is blocked with 403 when document_generator is not licensed"""
    assert rest_api.post(CHATGPT_MESSAGE_URL, json={}).status_code == HTTPStatus.FORBIDDEN


# -------------------------------------------------------------------------------------------------------------------- #
#                                          allowed when licensed / bypassed                                            #
# -------------------------------------------------------------------------------------------------------------------- #
def test_template_list_allowed_when_licensed(rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
    """With document_generator licensed the template-list read passes the guard"""
    monkeypatch.setattr(
        LicenseService,
        'has_feature',
        lambda _self, feature: feature == LicenseFeature.DOCUMENT_GENERATOR,
    )

    response = rest_api.get(TEMPLATE_LIST_URL)

    assert response.status_code == HTTPStatus.OK


def test_routes_not_gated_in_local_mode(rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
    """In local (cloud) mode the guard is bypassed even without a license"""
    monkeypatch.setattr(rest_api.application, 'local_mode', True)

    response = rest_api.get(TEMPLATE_LIST_URL)

    assert response.status_code == HTTPStatus.OK
