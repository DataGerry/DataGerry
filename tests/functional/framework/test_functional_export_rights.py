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
Who may export: the audience of the /exporter and /export/type routes

**The rule, decided 2026-09-21 (discussion-backlog #38): exporting is not a default user's
capability.** The seeded ``user`` group holds ``base.framework.object.*`` and a handful of view
rights, but no ``base.export.*`` - so a member of it may read objects and types through the API and
still may not take them away as a file. Only a group that is granted an export right explicitly (the
``admin`` group holds it through the master right) can.

That is a decision rather than an accident, which is exactly why it is pinned here: the object export
used to be guarded by ``base.framework.object.view``, a right the ``user`` group DOES hold, so before
the 2026-07-23 gating every non-admin user could export. Nothing failed when that changed, because no
test named the audience - this module is that test.

The other half is the *distinctness*: object export and type export ask for their own right, so a
group granted one of them does not get the other.
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.user_model import CmdbUser
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.group_model.group_constants import USER_GROUP_ID
from cmdb.interface.rest_api.routes.exporter_routes.exporter_constants import ExporterRight
# -------------------------------------------------------------------------------------------------------------------- #

OBJECT_EXPORT_URL: str = '/exporter'
TYPE_EXPORT_URL: str = '/export/type'

DEFAULT_USER_ID: int = 88701
OBJECT_EXPORTER_USER_ID: int = 88702
OBJECT_EXPORTER_GROUP_ID: int = 88703
PROBE_TYPE_ID: int = 88704

ALL_USER_IDS: list[int] = [DEFAULT_USER_ID, OBJECT_EXPORTER_USER_ID]

# Every guarded export route, with the right it must demand. The object export answers 200 with an
# empty file rather than 404, so a granted caller is visible in the status code
GUARDED_ROUTES: list[tuple[str, str, str]] = [
    ('extensions', f'{OBJECT_EXPORT_URL}/extensions', ExporterRight.OBJECT.value),
    ('objects', f'{OBJECT_EXPORT_URL}/?classname=JsonExportFormat&zip=false', ExporterRight.OBJECT.value),
    ('import-template', f'{OBJECT_EXPORT_URL}/template/{PROBE_TYPE_ID}', ExporterRight.OBJECT.value),
]

ROUTE_IDS: list[str] = [route[0] for route in GUARDED_ROUTES]


def _insert_user(database_manager: MongoDatabaseManager, database_name: str,
                 public_id: int, user_name: str, group_id: int) -> CmdbUser:
    """Stores an active CmdbUser in the given group and returns the model the test client sends as."""
    database_manager.get_collection(CmdbUser.COLLECTION, database_name).insert_one({
        'public_id': public_id,
        'user_name': user_name,
        'active': True,
        'group_id': group_id,
        'registration_time': datetime.now(timezone.utc),
        'api_level': 2,
        'config_items_limit': 1000,
        'database': database_name,
    })

    return CmdbUser(public_id=public_id, user_name=user_name, active=True, group_id=group_id)


@pytest.fixture(name='default_user', scope='module')
def fixture_default_user(database_manager: MongoDatabaseManager, database_name: str):
    """An authenticated user in the SEEDED 'user' group - the audience the decision is about."""
    user = _insert_user(database_manager, database_name, DEFAULT_USER_ID, 'export-default', USER_GROUP_ID)

    yield user

    database_manager.get_collection(CmdbUser.COLLECTION, database_name)\
        .delete_one({'public_id': DEFAULT_USER_ID})


@pytest.fixture(name='object_exporter_user', scope='module')
def fixture_object_exporter_user(database_manager: MongoDatabaseManager, database_name: str):
    """A user whose group is granted the OBJECT export right and nothing else from the export family."""
    groups = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
    groups.delete_many({'public_id': OBJECT_EXPORTER_GROUP_ID})
    groups.insert_one({
        'public_id': OBJECT_EXPORTER_GROUP_ID,
        'name': 'object-exporters',
        'label': 'Object Exporters',
        'rights': [ExporterRight.OBJECT.value],
    })

    user = _insert_user(database_manager, database_name, OBJECT_EXPORTER_USER_ID, 'export-objects-only',
                        OBJECT_EXPORTER_GROUP_ID)

    yield user

    database_manager.get_collection(CmdbUser.COLLECTION, database_name)\
        .delete_one({'public_id': OBJECT_EXPORTER_USER_ID})
    groups.delete_many({'public_id': OBJECT_EXPORTER_GROUP_ID})


class TestTheDefaultUserGroupMayNotExport:
    """The decision: a member of the seeded 'user' group is refused on every export route."""

    @pytest.mark.parametrize('label, url, right', GUARDED_ROUTES, ids=ROUTE_IDS)
    def test_the_object_export_routes_are_refused(self, rest_api, default_user: CmdbUser,
                                                  label: str, url: str, right: str) -> None:
        """Reading objects through /objects/ does not carry the right to take them away as a file."""
        del label, right

        assert rest_api.get(url, user=default_user).status_code == HTTPStatus.FORBIDDEN, url

    def test_the_type_export_routes_are_refused(self, rest_api, default_user: CmdbUser) -> None:
        """The type catalogue - which carries every Type's ACL block - is refused the same way."""
        for url in (f'{TYPE_EXPORT_URL}/', f'{TYPE_EXPORT_URL}/{PROBE_TYPE_ID}'):
            assert rest_api.post(url, user=default_user).status_code == HTTPStatus.FORBIDDEN, url

    def test_the_refusal_is_authorisation_not_authentication(self, rest_api, default_user: CmdbUser) -> None:
        """403, not 401: the user IS authenticated, and the same user may read what it may not export."""
        assert rest_api.get(f'{OBJECT_EXPORT_URL}/extensions', user=default_user).status_code \
            == HTTPStatus.FORBIDDEN
        assert rest_api.get('/objects/', user=default_user).status_code == HTTPStatus.OK


class TestTheTwoExportRightsAreDistinct:
    """Holding one export right is not holding the other - which is what makes them two rights."""

    def test_the_object_right_opens_the_object_export(self, rest_api,
                                                      object_exporter_user: CmdbUser) -> None:
        """Sanity check that the gate was not simply wired to deny everyone."""
        response = rest_api.get(f'{OBJECT_EXPORT_URL}/extensions', user=object_exporter_user)

        assert response.status_code == HTTPStatus.OK

    def test_the_object_right_does_not_open_the_type_export(self, rest_api,
                                                            object_exporter_user: CmdbUser) -> None:
        """A group granted object exports must not be able to take the type catalogue with it."""
        response = rest_api.post(f'{TYPE_EXPORT_URL}/', user=object_exporter_user)

        assert response.status_code == HTTPStatus.FORBIDDEN


class TestTheRightsTheRoutesAskFor:
    """
    WHICH right each route demands, recorded at the one place `.protect` consults

    The enforcement tests above cannot see a confusion between the two export rights: a default user is
    refused either way. This closes that gap the way the report and webhook right-mapping modules do.
    """

    API_BLUEPRINT_PATH: str = 'cmdb.interface.blueprints.api_blueprint.user_has_right'

    @pytest.mark.parametrize('label, url, expected_right', GUARDED_ROUTES, ids=ROUTE_IDS)
    def test_each_object_route_asks_for_the_object_export_right(
        self, rest_api, monkeypatch, label: str, url: str, expected_right: str,
    ) -> None:
        """The probe ids name nothing, so the assertion is on the recorded right, not on the answer."""
        del label
        asked: list[str] = []

        def _record(right: str, user: Any = None) -> bool:
            del user
            asked.append(right)

            return True

        monkeypatch.setattr(self.API_BLUEPRINT_PATH, _record)
        rest_api.get(url)

        assert expected_right in asked

    def test_the_type_routes_ask_for_the_type_export_right(self, rest_api, monkeypatch) -> None:
        """Both type-export routes demand base.export.type.*, not the object one."""
        asked: list[str] = []

        def _record(right: str, user: Any = None) -> bool:
            del user
            asked.append(right)

            return True

        monkeypatch.setattr(self.API_BLUEPRINT_PATH, _record)
        rest_api.post(f'{TYPE_EXPORT_URL}/')
        rest_api.post(f'{TYPE_EXPORT_URL}/{PROBE_TYPE_ID}')

        assert asked.count(ExporterRight.TYPE.value) == 2
        assert ExporterRight.OBJECT.value not in asked
