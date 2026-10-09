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
Integration tests for how the IPAM assignable-objects picker reads, against a real MongoDB

``build_assignable_objects_page`` with the real ObjectsManager / TypesManager over seeded documents:

- without a search MongoDB cuts the page: the pages together list every readable candidate exactly once, and the
  total is the count of them
- both paths list in public_id order (the candidates are stored in reverse, so the natural order would not be)
- only what a row reads is loaded: a candidate carrying a large ``multi_data_sections`` (its interface rows) still
  gets its row and summary line, and the documents the page reads carry no ``multi_data_sections``
- the caller's READ ACL scopes the count and the page alike: a denied type's objects are neither counted nor listed,
  with and without a search
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.ipam.assignable_objects import build_assignable_objects_page
from cmdb.manager import ObjectsManager, TypesManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID, USER_GROUP_ID
from cmdb.models.object_model import CmdbObject
from cmdb.models.special_type_model.ipam_constants import IpamOverviewKey, IpamSection
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

OPEN_TYPE_ID: int = 89301
HIDDEN_TYPE_ID: int = 89302
OPEN_OBJECT_IDS: list[int] = list(range(89311, 89318))     # seven readable candidates
HIDDEN_OBJECT_IDS: list[int] = [89321, 89322]               # of a type only the admin group may read
HEAVY_OBJECT_ID: int = OPEN_OBJECT_IDS[0]
ALL_OBJECT_IDS: list[int] = [*OPEN_OBJECT_IDS, *HIDDEN_OBJECT_IDS]
NAME_FIELD: str = 'dg-name'
HEAVY_ROWS: int = 500
PAGE_SIZE: int = 3


def _type_doc(public_id: int, label: str, acl: dict[str, Any]) -> dict[str, Any]:
    """An IPAM-capable type (it carries the dg-ipam-interface section)"""
    return {
        'public_id': public_id, 'name': f'paging-{public_id}', 'label': label, 'author_id': 1,
        'creation_time': datetime.now(timezone.utc), 'active': True,
        'fields': [{'type': 'text', 'name': NAME_FIELD, 'label': 'Name'}],
        'render_meta': {
            'icon': 'fa-cube',
            'sections': [{'name': IpamSection.INTERFACE, 'type': 'multi-data-section', 'label': 'IPAM Interface'}],
            'summary': {'fields': [NAME_FIELD]},
        },
        'ci_explorer_label': NAME_FIELD, 'ci_explorer_color': '#888', 'acl': acl, 'version': '1.0.0',
    }


def _object_doc(public_id: int, type_id: int, **extra: Any) -> dict[str, Any]:
    """A candidate whose summary line is its name"""
    return {
        'public_id': public_id, 'type_id': type_id, 'active': True, 'author_id': 1, 'version': '1.0.0',
        'creation_time': datetime.now(timezone.utc),
        'fields': [{'type': 'text', 'name': NAME_FIELD, 'value': f'host-{public_id}'}], **extra,
    }


@pytest.fixture(autouse=True)
def _app_context(rest_api):
    """Pushes the REST API app context so ManagerProvider (current_app.database_manager) resolves"""
    with rest_api.application.app_context():
        yield


@pytest.fixture(autouse=True)
def _seed(database_manager: MongoDatabaseManager, database_name: str):
    """Only this module's IPAM-capable types and candidates, in a clean slate"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    stashed_types: list[dict[str, Any]] = list(types.find({'render_meta.sections.name': IpamSection.INTERFACE}))

    def _purge() -> None:
        types.delete_many({'public_id': {'$in': [OPEN_TYPE_ID, HIDDEN_TYPE_ID]}})
        objects.delete_many({'public_id': {'$in': ALL_OBJECT_IDS}})

    _purge()
    # Other modules' IPAM-capable types would add their objects to the candidates; park them for the test
    types.delete_many({'render_meta.sections.name': IpamSection.INTERFACE})
    types.insert_many([
        _type_doc(OPEN_TYPE_ID, 'Open', {'activated': False, 'groups': {'includes': {}}}),
        _type_doc(HIDDEN_TYPE_ID, 'Hidden',
                  {'activated': True, 'groups': {'includes': {str(ADMIN_GROUP_ID): ['READ']}}}),
    ])
    heavy_mds: list[dict[str, Any]] = [{'section_id': IpamSection.INTERFACE, 'highest_id': HEAVY_ROWS, 'values': [
        {'multi_data_id': row, 'data': [{'name': 'ip', 'value': f'10.0.{row // 256}.{row % 256}'}]}
        for row in range(HEAVY_ROWS)
    ]}]
    # Stored in REVERSE id order, so MongoDB's natural order is not id order - a missing sort shows
    objects.insert_many(list(reversed([
        _object_doc(HEAVY_OBJECT_ID, OPEN_TYPE_ID, multi_data_sections=heavy_mds),
        *[_object_doc(public_id, OPEN_TYPE_ID) for public_id in OPEN_OBJECT_IDS[1:]],
        *[_object_doc(public_id, HIDDEN_TYPE_ID) for public_id in HIDDEN_OBJECT_IDS],
    ])))
    yield
    _purge()
    if stashed_types:
        types.insert_many(stashed_types)


def _user(group_id: int) -> CmdbUser:
    """A request user of the given group"""
    return CmdbUser(public_id=1, user_name='paging', active=True, group_id=group_id)


def _page(page: int, user: CmdbUser, search: str = '', page_size: int = PAGE_SIZE) -> dict[str, Any]:
    """One page of the picker as the user"""
    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, user)
    types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, user)

    return build_assignable_objects_page(
        objects_manager, types_manager, page=page, page_size=page_size, search=search, request_user=user,
    )


def _ids(payload: dict[str, Any]) -> list[int]:
    """The listed public_ids"""
    return [row['public_id'] for row in payload[IpamOverviewKey.ROWS]]


class TestThePagesWithoutASearch:
    """MongoDB cuts the page; together the pages are the candidate set."""

    @pytest.mark.parametrize('group_id, expected', [
        (ADMIN_GROUP_ID, ALL_OBJECT_IDS), (USER_GROUP_ID, OPEN_OBJECT_IDS),
    ], ids=['admin', 'user'])
    def test_every_readable_candidate_is_listed_exactly_once(self, group_id: int, expected: list[int]) -> None:
        """Pages of three cover the readable set without repeats, and every page states the same total"""
        first: dict[str, Any] = _page(1, _user(group_id))
        pages: list[dict[str, Any]] = [
            first, *[_page(number, _user(group_id)) for number in range(2, -(-len(expected) // PAGE_SIZE) + 1)],
        ]
        listed: list[int] = [public_id for payload in pages for public_id in _ids(payload)]

        assert sorted(listed) == sorted(expected)
        assert len(listed) == len(set(listed))
        assert {payload[IpamOverviewKey.TOTAL] for payload in pages} == {len(expected)}

    def test_a_page_holds_at_most_the_page_size(self) -> None:
        """The cut is the driver's: no page is longer than asked"""
        assert len(_ids(_page(1, _user(ADMIN_GROUP_ID)))) == PAGE_SIZE


class TestTheOrder:
    """public_id ascending, on both paths - the candidates are stored in reverse, so natural order would not be."""

    def test_the_pages_together_are_in_strictly_ascending_id_order(self) -> None:
        """Page 1, 2, 3 of three each, concatenated: every id once, ascending"""
        listed: list[int] = [
            public_id for number in range(1, -(-len(ALL_OBJECT_IDS) // PAGE_SIZE) + 1)
            for public_id in _ids(_page(number, _user(ADMIN_GROUP_ID)))
        ]

        assert listed == sorted(ALL_OBJECT_IDS)

    def test_a_page_is_the_same_rows_on_every_request(self) -> None:
        """Stable: asking twice answers the same page"""
        assert _ids(_page(2, _user(ADMIN_GROUP_ID))) == _ids(_page(2, _user(ADMIN_GROUP_ID)))

    def test_a_search_lists_in_id_order(self) -> None:
        """The filtered rows are cut from an id-ordered read"""
        listed: list[int] = _ids(_page(1, _user(ADMIN_GROUP_ID), search='host-', page_size=len(ALL_OBJECT_IDS)))

        assert listed == sorted(ALL_OBJECT_IDS)


class TestOnlyWhatARowReadsIsLoaded:
    """The interface rows are never read."""

    def test_a_candidate_with_many_interface_rows_gets_its_row(self) -> None:
        """The heavy candidate is listed with its summary line"""
        payload: dict[str, Any] = _page(1, _user(ADMIN_GROUP_ID), page_size=len(ALL_OBJECT_IDS))
        row: dict[str, Any] = next(row for row in payload[IpamOverviewKey.ROWS] if row['public_id'] == HEAVY_OBJECT_ID)

        assert f'host-{HEAVY_OBJECT_ID}' in row[IpamOverviewKey.SUMMARY_LINE]
        assert row[IpamOverviewKey.TYPE_INFO][IpamOverviewKey.LABEL] == 'Open'

    @pytest.mark.parametrize('search', ['', 'host-'], ids=['unsearched', 'searched'])
    def test_the_documents_read_carry_no_interface_rows(self, search: str, monkeypatch: pytest.MonkeyPatch) -> None:
        """Spy on the read: what reaches the row builder has public_id, type_id and fields only"""
        read: list[dict[str, Any]] = []
        original = ObjectsManager.find_objects

        def _spy(self, *args: Any, **kwargs: Any):
            documents = original(self, *args, **kwargs)
            read.extend(documents)
            return documents

        monkeypatch.setattr(ObjectsManager, 'find_objects', _spy)

        _page(1, _user(ADMIN_GROUP_ID), search=search, page_size=len(ALL_OBJECT_IDS))

        assert read
        assert all(set(document) <= {'public_id', 'type_id', 'fields'} for document in read)


class TestTheAcl:
    """The count and the page are scoped alike."""

    def test_a_denied_type_is_neither_counted_nor_listed(self) -> None:
        """The user group may not read the hidden type"""
        payload: dict[str, Any] = _page(1, _user(USER_GROUP_ID), page_size=len(ALL_OBJECT_IDS))

        assert payload[IpamOverviewKey.TOTAL] == len(OPEN_OBJECT_IDS)
        assert not set(_ids(payload)) & set(HIDDEN_OBJECT_IDS)

    def test_a_search_is_scoped_too(self) -> None:
        """The same with a search that every candidate's summary line matches"""
        payload: dict[str, Any] = _page(1, _user(USER_GROUP_ID), search='host-', page_size=len(ALL_OBJECT_IDS))

        assert payload[IpamOverviewKey.TOTAL] == len(OPEN_OBJECT_IDS)
        assert sorted(_ids(payload)) == OPEN_OBJECT_IDS
