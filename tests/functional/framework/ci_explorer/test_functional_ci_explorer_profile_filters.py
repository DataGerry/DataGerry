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
What a CI Explorer profile's two filters may hold, and what a type delete does to them

**An empty filter means "no restriction"** - the frontend leaves it out of the graph request - so a
filter is a list of integer ids, each naming an existing CmdbType / CmdbRelation, and the write routes
refuse anything else where it is written rather than letting the graph refuse it later. And a type
delete must never empty a narrow profile's filter: a profile whose types_filter held the deleted type
alone is deleted, while one keeping other types is only narrowed
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.ci_explorer_model import CiExplorerProfileKey, CmdbCiExplorerProfile
from cmdb.models.relation_model.cmdb_relation import CmdbRelation
from cmdb.models.type_model import CmdbType
from cmdb.interface.rest_api.routes.ci_explorer_routes.ci_explorer_constants import PROFILE_FILTER_UNKNOWN_IDS_MSG
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

PROFILE_URL: str = '/ci_explorer/profile'
TYPE_URL: str = '/types'

KEPT_TYPE_ID: int = 99301
DOOMED_TYPE_ID: int = 99302
RELATION_ID: int = 99311
UNKNOWN_ID: int = 99399
ONLY_DOOMED_PROFILE_ID: int = 99321
MIXED_PROFILE_ID: int = 99322
UPDATE_PROFILE_ID: int = 99323

PROFILE_NAME: str = 'profile-filters'
ALL_PROFILE_IDS: list[int] = [ONLY_DOOMED_PROFILE_ID, MIXED_PROFILE_ID, UPDATE_PROFILE_ID]

TYPES_FILTER: str = CiExplorerProfileKey.TYPES_FILTER.value
RELATIONS_FILTER: str = CiExplorerProfileKey.RELATIONS_FILTER.value


def _payload(types_filter: list[Any] | None = None, relations_filter: list[Any] | None = None) -> dict[str, Any]:
    """A profile write body."""
    return {
        'name': PROFILE_NAME,
        TYPES_FILTER: types_filter if types_filter is not None else [],
        RELATIONS_FILTER: relations_filter if relations_filter is not None else [],
        'with_locations': True,
        'with_ipam_relations': False,
    }


@pytest.fixture(autouse=True)
def _seed(database_manager: MongoDatabaseManager, database_name: str):
    """Two types, one relation and three profiles; removes them and every profile this module created."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    relations = database_manager.get_collection(CmdbRelation.COLLECTION, database_name)
    profiles = database_manager.get_collection(CmdbCiExplorerProfile.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': {'$in': [KEPT_TYPE_ID, DOOMED_TYPE_ID]}})
        relations.delete_many({'public_id': RELATION_ID})
        profiles.delete_many({'$or': [{'public_id': {'$in': ALL_PROFILE_IDS}}, {'name': PROFILE_NAME}]})

    _purge()
    types.insert_many([make_type_doc(KEPT_TYPE_ID, 'profile-filter-kept'),
                       make_type_doc(DOOMED_TYPE_ID, 'profile-filter-doomed')])
    relations.insert_one({'public_id': RELATION_ID, 'relation_name': 'profile-filter-relation',
                          'creation_time': datetime.now(timezone.utc)})
    profiles.insert_many([
        {'public_id': ONLY_DOOMED_PROFILE_ID, **_payload([DOOMED_TYPE_ID]), 'name': 'only-doomed'},
        {'public_id': MIXED_PROFILE_ID, **_payload([DOOMED_TYPE_ID, KEPT_TYPE_ID]), 'name': 'mixed'},
        {'public_id': UPDATE_PROFILE_ID, **_payload(), 'name': 'to-update'},
    ])
    yield
    _purge()


def _stored(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> dict[str, Any] | None:
    """Reads a profile back from the collection."""
    return database_manager.get_collection(CmdbCiExplorerProfile.COLLECTION, database_name)\
        .find_one({'public_id': public_id})


class TestWhatAFilterMayHold:
    """The write routes accept integer ids of existing types and relations, and empty lists."""

    def test_existing_ids_are_accepted(self, rest_api) -> None:
        """A type and a relation that exist"""
        response = rest_api.post(PROFILE_URL, json=_payload([KEPT_TYPE_ID], [RELATION_ID]))

        assert response.status_code == HTTPStatus.CREATED

    def test_empty_filters_are_accepted(self, rest_api) -> None:
        """Empty means "no restriction" - a profile narrowing nothing is a valid profile"""
        assert rest_api.post(PROFILE_URL, json=_payload()).status_code == HTTPStatus.CREATED

    @pytest.mark.parametrize('bad_entry', ['x', 0, -1, 1.5, {'id': 1}])
    @pytest.mark.parametrize('field', [TYPES_FILTER, RELATIONS_FILTER])
    def test_a_non_id_entry_is_refused(self, rest_api, field: str, bad_entry: Any) -> None:
        """Only positive integers - anything else made the graph answer 400 when the profile was applied"""
        body: dict[str, Any] = _payload()
        body[field] = [bad_entry]

        assert rest_api.post(PROFILE_URL, json=body).status_code == HTTPStatus.BAD_REQUEST

    @pytest.mark.parametrize('field', [TYPES_FILTER, RELATIONS_FILTER])
    def test_an_unknown_id_is_refused_by_name(self, rest_api, field: str) -> None:
        """An id naming nothing would filter the graph to nothing - refused, naming the filter and the id"""
        body: dict[str, Any] = _payload()
        body[field] = [UNKNOWN_ID]

        response = rest_api.post(PROFILE_URL, json=body)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == PROFILE_FILTER_UNKNOWN_IDS_MSG.format(field=field, ids=[UNKNOWN_ID])

    def test_the_update_route_refuses_an_unknown_id_too(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Same rule on PUT - and the stored profile is left as it was"""
        response = rest_api.put(f'{PROFILE_URL}/{UPDATE_PROFILE_ID}', json=_payload([KEPT_TYPE_ID, UNKNOWN_ID]))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _stored(database_manager, database_name, UPDATE_PROFILE_ID)[TYPES_FILTER] == []


class TestATypeDelete:
    """DELETE /types/<id> and the profiles naming that type."""

    def test_a_profile_holding_the_type_alone_is_deleted(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Pulling its last type would have widened it to every type - it is gone instead"""
        assert rest_api.delete(f'{TYPE_URL}/{DOOMED_TYPE_ID}').status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)

        assert _stored(database_manager, database_name, ONLY_DOOMED_PROFILE_ID) is None

    def test_a_profile_keeping_other_types_is_only_narrowed(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The deleted type is pulled; the profile stays with the types it still names"""
        rest_api.delete(f'{TYPE_URL}/{DOOMED_TYPE_ID}')

        assert _stored(database_manager, database_name, MIXED_PROFILE_ID)[TYPES_FILTER] == [KEPT_TYPE_ID]

    def test_a_profile_saved_without_a_type_filter_is_untouched(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """An empty filter it was saved with means "all types" and is no business of the delete"""
        rest_api.delete(f'{TYPE_URL}/{DOOMED_TYPE_ID}')

        assert _stored(database_manager, database_name, UPDATE_PROFILE_ID)[TYPES_FILTER] == []
