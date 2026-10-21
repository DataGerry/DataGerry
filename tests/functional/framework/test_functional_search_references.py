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
What `/search/` and the quick-search count answer for a term that is found through a reference

Over HTTP, against seeded documents: an object is found through a REFERENCE row pointing at a matching
object, never through a number that equals an object's id, never through an object the caller may not
read; a hit is rendered from the object as stored, so its editor and its multi-data sections are there
and a referenced object's value never shows as its own; and the count the search bar shows is the
number of objects the search then lists
"""
import json
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.rendering.render_constants import RenderObjectInfoKey
from cmdb.framework.search.search_constants import (
    SearchFormType,
    SearchQueryKey,
    SearchResultKey,
    SearchResultMapKey,
)
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID, USER_GROUP_ID
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

SEARCH_URL: str = '/search/'
QUICK_COUNT_URL: str = '/search/quick/count/'

OPEN_TYPE_ID: int = 47701
HIDDEN_TYPE_ID: int = 47702

TARGET_ID: int = 47711
NUMBER_ID: int = 47712
REFERRER_ID: int = 47713
EDITED_ID: int = 47714
HIDDEN_ID: int = 47715
HIDDEN_REFERRER_ID: int = 47716
ALL_OBJECT_IDS: list[int] = [TARGET_ID, NUMBER_ID, REFERRER_ID, EDITED_ID, HIDDEN_ID, HIDDEN_REFERRER_ID]

SEARCH_USER_ID: int = 47721

TARGET_TERM: str = 'Router-Q7'
EDITED_TERM: str = 'edited-host-Q7'
HIDDEN_TERM: str = 'secret-token-Q7'
OWNER_VALUE: str = 'NetOps-Q7'   # stored by the target only
EDITOR_ID: int = 1
MDS: list[dict[str, Any]] = [{'section_id': 'mds', 'values': []}]
# A pattern MongoDB refuses to compile
UNCOMPILABLE_TERM: str = '[unclosed'

HOSTNAME: str = 'hostname'
OWNER: str = 'owner'
UPLINK: str = 'uplink'
UNITS: str = 'rack_units'


def _type_doc(public_id: int, acl: dict[str, Any]) -> dict[str, Any]:
    """A type declaring the four fields, all in one section, with the given ACL."""
    fields: list[dict[str, Any]] = [
        {'type': 'text', 'name': HOSTNAME, 'label': 'Hostname'},
        {'type': 'text', 'name': OWNER, 'label': 'Owner'},
        {'type': 'number', 'name': UNITS, 'label': 'Units'},
        {'type': 'ref', 'name': UPLINK, 'label': 'Uplink', 'ref_types': [OPEN_TYPE_ID, HIDDEN_TYPE_ID]},
    ]

    return {
        'public_id': public_id, 'name': f'search-refs-{public_id}', 'label': f'Search Refs {public_id}',
        'author_id': 1, 'creation_time': datetime.now(timezone.utc), 'active': True, 'fields': fields,
        'render_meta': {
            'icon': 'fa-cube',
            'sections': [{'type': 'section', 'name': 'main', 'label': 'Main',
                          'fields': [field['name'] for field in fields]}],
            'summary': {'fields': [HOSTNAME]},
        },
        'acl': acl, 'version': '1.0.0',
    }


def _object_doc(public_id: int, rows: list[dict[str, Any]], type_id: int = OPEN_TYPE_ID,
                **extra: Any) -> dict[str, Any]:
    """A stored object carrying `rows`."""
    return {
        'public_id': public_id, 'type_id': type_id, 'active': True, 'author_id': 1, 'version': '1.0.0',
        'creation_time': datetime.now(timezone.utc), 'fields': rows, 'multi_data_sections': [], **extra,
    }


@pytest.fixture(autouse=True)
def _seed(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds an open and a hidden type, the objects and a user of the default group; removes them after."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': {'$in': [OPEN_TYPE_ID, HIDDEN_TYPE_ID]}})
        objects.delete_many({'public_id': {'$in': ALL_OBJECT_IDS}})
        users.delete_many({'public_id': SEARCH_USER_ID})

    _purge()
    types.insert_many([
        _type_doc(OPEN_TYPE_ID, {'activated': False, 'groups': {'includes': None}}),
        _type_doc(HIDDEN_TYPE_ID, {'activated': True, 'groups': {'includes': {str(ADMIN_GROUP_ID): ['READ']}}}),
    ])
    objects.insert_many([
        _object_doc(TARGET_ID, [{'type': 'text', 'name': HOSTNAME, 'value': TARGET_TERM},
                                {'type': 'text', 'name': OWNER, 'value': OWNER_VALUE}]),
        _object_doc(NUMBER_ID, [{'type': 'text', 'name': HOSTNAME, 'value': 'alpha-Q7'},
                                {'type': 'number', 'name': UNITS, 'value': TARGET_ID}]),
        # No 'owner' row: the target's owner must not render as the referrer's
        _object_doc(REFERRER_ID, [{'type': 'text', 'name': HOSTNAME, 'value': 'beta-Q7'},
                                  {'type': 'ref', 'name': UPLINK, 'value': TARGET_ID}]),
        _object_doc(EDITED_ID, [{'type': 'text', 'name': HOSTNAME, 'value': EDITED_TERM}],
                    editor_id=EDITOR_ID, last_edit_time=datetime.now(timezone.utc), multi_data_sections=MDS),
        _object_doc(HIDDEN_ID, [{'type': 'text', 'name': HOSTNAME, 'value': HIDDEN_TERM}], type_id=HIDDEN_TYPE_ID),
        _object_doc(HIDDEN_REFERRER_ID, [{'type': 'text', 'name': HOSTNAME, 'value': 'zeta-Q7'},
                                         {'type': 'ref', 'name': UPLINK, 'value': HIDDEN_ID}]),
    ])
    users.insert_one({'public_id': SEARCH_USER_ID, 'user_name': 'search-refs-user', 'active': True,
                      'group_id': USER_GROUP_ID, 'registration_time': datetime.now(timezone.utc)})
    yield
    _purge()


def _default_user() -> CmdbUser:
    """The seeded member of the default 'user' group."""
    return CmdbUser(public_id=SEARCH_USER_ID, user_name='search-refs-user', active=True, group_id=USER_GROUP_ID)


def _search(rest_api, term: str, **kwargs: Any) -> dict[str, Any]:
    """POSTs a one-term TEXT search and answers the body."""
    body: str = json.dumps([{'searchText': term, 'searchForm': SearchFormType.TEXT.value}])
    response = rest_api.post(f'{SEARCH_URL}?limit=0', data=body, content_type='application/json', **kwargs)

    assert response.status_code == HTTPStatus.OK

    return response.get_json()


def _hits(body: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """The rendered hits of a search body, by object id."""
    return {
        hit[SearchResultMapKey.RESULT.value]['object_information'][RenderObjectInfoKey.OBJECT_ID.value]:
            hit[SearchResultMapKey.RESULT.value]
        for hit in body[SearchResultKey.RESULTS.value]
    }


def _field_value(rendered: dict[str, Any], name: str) -> Any:
    """The rendered value of one field."""
    return next(field['value'] for field in rendered['fields'] if field['name'] == name)


class TestWhatTheSearchFinds:
    """A reference row finds its referrer; a number never does."""

    def test_the_target_and_its_referrer_are_found(self, rest_api) -> None:
        """The target by its own value, the referrer through its reference"""
        assert {TARGET_ID, REFERRER_ID} <= set(_hits(_search(rest_api, TARGET_TERM)))

    def test_a_number_equal_to_the_targets_id_is_not(self, rest_api) -> None:
        """A number field holding the target's id is a number"""
        assert NUMBER_ID not in _hits(_search(rest_api, TARGET_TERM))


class TestAHitIsRenderedAsStored:
    """The rendered hit is the object - its editor, its sections, its own values."""

    def test_the_editor_is_rendered(self, rest_api) -> None:
        """A hit carries its editor - otherwise every hit reads as never edited"""
        rendered: dict[str, Any] = _hits(_search(rest_api, EDITED_TERM))[EDITED_ID]

        assert rendered['object_information'][RenderObjectInfoKey.EDITOR_ID.value] == EDITOR_ID

    def test_the_multi_data_sections_are_rendered(self, rest_api) -> None:
        """And its multi-data sections"""
        rendered: dict[str, Any] = _hits(_search(rest_api, EDITED_TERM))[EDITED_ID]

        assert rendered['multi_data_sections'] == MDS

    def test_a_referenced_objects_value_is_not_the_referrers(self, rest_api) -> None:
        """The referrer stores no owner, so it renders none - not the target's"""
        rendered: dict[str, Any] = _hits(_search(rest_api, TARGET_TERM))[REFERRER_ID]

        assert _field_value(rendered, OWNER) != OWNER_VALUE


class TestTheCallersAcl:
    """An object the caller may not read cannot be used to find another."""

    def test_the_default_user_does_not_find_the_referrer_of_a_hidden_object(self, rest_api) -> None:
        """The user group may not read the hidden type"""
        found: dict[int, Any] = _hits(_search(rest_api, HIDDEN_TERM, user=_default_user()))

        assert HIDDEN_REFERRER_ID not in found
        assert HIDDEN_ID not in found

    def test_the_admin_does(self, rest_api) -> None:
        """The admin group may read it, so the reference is followed"""
        assert HIDDEN_REFERRER_ID in _hits(_search(rest_api, HIDDEN_TERM))


class TestTheQuickCountAgrees:
    """The number beside the search bar is the number of hits the search then lists."""

    @pytest.mark.parametrize('term', [TARGET_TERM, HIDDEN_TERM, EDITED_TERM])
    @pytest.mark.parametrize('as_default_user', [False, True], ids=['admin', 'default-user'])
    def test_the_count_equals_the_total(self, rest_api, term: str, as_default_user: bool) -> None:
        """Same term, same caller, same answer"""
        extra: dict[str, Any] = {'user': _default_user()} if as_default_user else {}

        count = rest_api.get(QUICK_COUNT_URL, query_string={SearchQueryKey.SEARCH_VALUE.value: term}, **extra)

        assert count.status_code == HTTPStatus.OK
        assert count.get_json()['total'] == _search(rest_api, term, **extra)[SearchResultKey.TOTAL_RESULTS.value]

    def test_a_term_mongodb_refuses_is_still_a_400(self, rest_api) -> None:
        """
        The quick count's term is a raw pattern; one MongoDB cannot compile is the caller's problem

        Building the pipeline now queries too, so the refusal can come from there - it is answered the
        same way as a refusal of the count itself
        """
        response = rest_api.get(QUICK_COUNT_URL, query_string={SearchQueryKey.SEARCH_VALUE.value: UNCOMPILABLE_TERM})

        assert response.status_code == HTTPStatus.BAD_REQUEST
