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
Unit tests for cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_operations_helper

Every Type document of an answer gets the caller's allowed operations from one engine call, and the ``acl`` the access
rules decide in place of the stored one from one more; a document without an integer public_id - or, for the ``acl``,
without one - is left as it is; the category tree's Types are found at any depth, in tree order
"""
from typing import Any

import pytest

from cmdb.interface.rest_api.routes.framework_routes.cmdb_types import types_operations_helper
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_operations_helper import (
    tree_types,
    with_allowed_operations,
    with_synthesised_acl,
)
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

USER: CmdbUser = CmdbUser(public_id=51, user_name='operations', active=True, group_ids=[21])
SERVER_TYPE_ID: int = 11
ROUTER_TYPE_ID: int = 12
FREE_TYPE_ID: int = 13
ANSWER: dict[int, list[str]] = {SERVER_TYPE_ID: ['view'], ROUTER_TYPE_ID: [],
                                FREE_TYPE_ID: ['view', 'create', 'edit', 'delete']}


def _type(public_id: Any) -> dict[str, Any]:
    """A Type document"""
    return {'public_id': public_id, 'name': f'type-{public_id}'}


def test_every_type_gets_its_operations_from_one_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """One call with every id; each document its own list"""
    asked: list[Any] = []
    monkeypatch.setattr(types_operations_helper, 'allowed_operation_values',
                        lambda user, ids: asked.append((user, list(ids))) or ANSWER)
    documents: list[dict[str, Any]] = [_type(SERVER_TYPE_ID), _type(ROUTER_TYPE_ID), _type(FREE_TYPE_ID)]

    with_allowed_operations(documents, USER)

    assert asked == [(USER, [SERVER_TYPE_ID, ROUTER_TYPE_ID, FREE_TYPE_ID])]
    assert [document['allowed_operations'] for document in documents] == [
        ['view'], [], ['view', 'create', 'edit', 'delete']]


def test_a_document_without_an_integer_id_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    """A projection that left the id out"""
    monkeypatch.setattr(types_operations_helper, 'allowed_operation_values', lambda user, ids: {})
    documents: list[dict[str, Any]] = [{'name': 'no-id'}, _type('11')]

    with_allowed_operations(documents, USER)

    assert all('allowed_operations' not in document for document in documents)


def test_tree_types_at_any_depth_in_tree_order() -> None:
    """Roots first, then their children"""
    tree: list[dict[str, Any]] = [
        {'category': {}, 'types': [_type(SERVER_TYPE_ID)],
         'children': [{'category': {}, 'types': [_type(FREE_TYPE_ID)], 'children': []}]},
        {'category': {}, 'types': [_type(ROUTER_TYPE_ID)], 'children': []},
    ]

    assert [document['public_id'] for document in tree_types(tree)] == [SERVER_TYPE_ID, ROUTER_TYPE_ID, FREE_TYPE_ID]


STORED_ACL: dict[str, Any] = {'activated': True, 'groups': {'includes': {'99': ['READ']}}}
SYNTHESISED: dict[int, dict[str, Any]] = {
    SERVER_TYPE_ID: {'activated': True, 'groups': {'includes': {'21': ['READ']}}},
    ROUTER_TYPE_ID: {'activated': False, 'groups': {'includes': {}}},
}


def test_every_acl_is_replaced_by_the_synthesised_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """One call with the ids carrying an acl; each document its own block"""
    asked: list[Any] = []
    monkeypatch.setattr(types_operations_helper, 'synthesised_acl_values',
                        lambda user, ids: asked.append((user, list(ids))) or SYNTHESISED)
    documents: list[dict[str, Any]] = [{**_type(SERVER_TYPE_ID), 'acl': STORED_ACL},
                                       {**_type(ROUTER_TYPE_ID), 'acl': STORED_ACL}]

    with_synthesised_acl(documents, USER)

    assert asked == [(USER, [SERVER_TYPE_ID, ROUTER_TYPE_ID])]
    assert [document['acl'] for document in documents] == [SYNTHESISED[SERVER_TYPE_ID], SYNTHESISED[ROUTER_TYPE_ID]]


def test_a_document_without_an_acl_or_an_int_id_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    """A projection without the acl gets none; nothing to replace reads nothing"""
    asked: list[Any] = []
    monkeypatch.setattr(types_operations_helper, 'synthesised_acl_values',
                        lambda user, ids: asked.append(ids) or {})
    documents: list[dict[str, Any]] = [_type(SERVER_TYPE_ID), {'name': 'no-id', 'acl': STORED_ACL}]

    with_synthesised_acl(documents, USER)

    assert asked == []
    assert 'acl' not in documents[0] and documents[1]['acl'] is STORED_ACL
