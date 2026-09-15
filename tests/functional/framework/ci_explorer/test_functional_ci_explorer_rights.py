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
ACL rights of the /ci_explorer routes

Every route is driven twice with `user_has_right` patched at the api_blueprint module path - the one
place `.protect` consults: once granting, to record WHICH right the route asks for, and once denying,
to prove it answers 403 instead of running. Together they pin the right-per-route table; the default
test user holds every right, so an unpatched suite can never notice a missing guard

The CI Explorer right family has two members, so the reads take VIEW and every write takes EDIT -
profile creation and deletion included
"""
from http import HTTPStatus
from typing import Any, Callable

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.ci_explorer_model import CmdbCiExplorerProfile
from cmdb.interface.rest_api.routes.ci_explorer_routes.ci_explorer_constants import CiExplorerRight
# -------------------------------------------------------------------------------------------------------------------- #

API_BLUEPRINT_PATH: str = 'cmdb.interface.blueprints.api_blueprint.user_has_right'
ROUTE_URL: str = '/ci_explorer'
PROBE_ID: int = 99510
PROFILE_NAME: str = 'rights-probe-profile'

PROFILE_BODY: dict[str, Any] = {
    'name': PROFILE_NAME,
    'types_filter': [],
    'relations_filter': [],
    'with_locations': False,
    'with_ipam_relations': False,
}
TOOLTIP_BODY: dict[str, Any] = {'ci_explorer_tooltip': 'probe'}
LABEL_BODY: dict[str, Any] = {'ci_explorer_label': 'name'}

# (label, HTTP method, URL, body, the right the route must ask for)
GUARDED_ROUTES: list[tuple[str, str, str, dict[str, Any] | None, str]] = [
    ('insert_profile', 'POST', f'{ROUTE_URL}/profile', PROFILE_BODY, CiExplorerRight.EDIT.value),
    ('get_profiles', 'GET', f'{ROUTE_URL}/profile', None, CiExplorerRight.VIEW.value),
    ('get_nodes_edges', 'GET', f'{ROUTE_URL}/items?target_id={PROBE_ID}', None, CiExplorerRight.VIEW.value),
    ('update_tooltip', 'PUT', f'{ROUTE_URL}/tooltip/{PROBE_ID}', TOOLTIP_BODY, CiExplorerRight.EDIT.value),
    ('update_type_label', 'PUT', f'{ROUTE_URL}/type_label/{PROBE_ID}', LABEL_BODY, CiExplorerRight.EDIT.value),
    ('update_profile', 'PUT', f'{ROUTE_URL}/profile/{PROBE_ID}', PROFILE_BODY, CiExplorerRight.EDIT.value),
    ('delete_profile', 'DELETE', f'{ROUTE_URL}/profile/{PROBE_ID}', None, CiExplorerRight.EDIT.value),
]

ROUTE_IDS: list[str] = [route[0] for route in GUARDED_ROUTES]


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes the profile the granting run of the create route really writes."""
    def _purge() -> None:
        database_manager.get_collection(CmdbCiExplorerProfile.COLLECTION, database_name)\
                        .delete_many({'name': PROFILE_NAME})

    _purge()
    yield
    _purge()


def _call(rest_api, method: str, url: str, body: dict[str, Any] | None):
    """Issues the request with the verb the route is registered for."""
    verb: Callable[..., Any] = getattr(rest_api, method.lower())

    return verb(url, json=body) if body is not None else verb(url)


@pytest.mark.parametrize('label, method, url, body, expected_right', GUARDED_ROUTES, ids=ROUTE_IDS)
def test_route_asks_for_its_own_right(rest_api, monkeypatch, label, method, url, body, expected_right) -> None:
    """Each route asks `.protect` for exactly the right of its operation."""
    del label
    asked_rights: list[str] = []

    def _record(right: str, user: Any = None) -> bool:
        del user
        asked_rights.append(right)

        return True

    monkeypatch.setattr(API_BLUEPRINT_PATH, _record)

    _call(rest_api, method, url, body)

    assert asked_rights == [expected_right]


@pytest.mark.parametrize('label, method, url, body, expected_right', GUARDED_ROUTES, ids=ROUTE_IDS)
def test_route_without_the_right_is_forbidden(rest_api, monkeypatch, label, method, url, body,
                                              expected_right) -> None:
    """A user lacking the right gets 403 and the handler never runs."""
    del label, expected_right

    monkeypatch.setattr(API_BLUEPRINT_PATH, lambda right, user=None: False)

    assert _call(rest_api, method, url, body).status_code == HTTPStatus.FORBIDDEN
