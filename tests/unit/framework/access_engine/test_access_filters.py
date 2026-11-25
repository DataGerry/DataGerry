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
Unit tests for cmdb.framework.access_engine.access_filters

Past a stubbed load_grants and ManagerProvider: each function answers from the user's grants; denied_type_ids reads
the existing Types and the objects' Type ids only for a complement; scope_filter for one Type answers no filter or one no object matches
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.framework.access_engine import access_filters
from cmdb.framework.access_engine import (
    AccessGrants,
    DeniedTypes,
    build_grants,
    denied_type_ids,
    denied_types,
    allowed_operation_values,
    operations_on_types,
    permitted_types_criteria,
    scope_filter,
    type_allows,
)
from cmdb.manager.manager_provider_model import ManagerType
from cmdb.models.access_model import ScopeOperation
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

SERVER_TYPE_ID: int = 11
ROUTER_TYPE_ID: int = 12
SWITCH_TYPE_ID: int = 13
GONE_TYPE_ID: int = 19
USER_GROUP_ID: int = 21
OTHER_GROUP_ID: int = 23
USER: CmdbUser = CmdbUser(public_id=51, user_name='reader', active=True, group_ids=[USER_GROUP_ID])
VIEW = ScopeOperation.VIEW
EDIT = ScopeOperation.EDIT

# The user may view servers; another group's role restricts routers
FINITE_GRANTS: AccessGrants = build_grants(
    [{'public_id': 41, 'group_id': USER_GROUP_ID, 'role_id': 31, 'scope': '*'}],
    [{'public_id': 31, 'types': [SERVER_TYPE_ID], 'operations': ['view']},
     {'public_id': 32, 'types': [ROUTER_TYPE_ID], 'operations': ['view']}],
    [USER_GROUP_ID],
)
# The user may view servers; another group's role restricts every Type
COMPLEMENT_GRANTS: AccessGrants = build_grants(
    [{'public_id': 41, 'group_id': USER_GROUP_ID, 'role_id': 31, 'scope': '*'}],
    [{'public_id': 31, 'types': [SERVER_TYPE_ID], 'operations': ['view']},
     {'public_id': 32, 'types': '*', 'operations': ['view']}],
    [USER_GROUP_ID],
)


@pytest.fixture(name='engine')
def fixture_engine(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """load_grants answering the finite grants (switchable), a ManagerProvider whose Types are the three and whose
    objects carry those, a gone Type's id and junk"""
    state: dict[str, Any] = {'grants': FINITE_GRANTS, 'types': MagicMock(), 'objects': MagicMock()}
    state['types'].get_all_type_ids.return_value = [SERVER_TYPE_ID, ROUTER_TYPE_ID, SWITCH_TYPE_ID]
    state['objects'].get_distinct.return_value = [SERVER_TYPE_ID, ROUTER_TYPE_ID, GONE_TYPE_ID, None, True, 'x']
    provider = MagicMock()
    provider.get_manager.side_effect = lambda kind, _user: {ManagerType.TYPES: state['types'],
                                                            ManagerType.OBJECTS: state['objects']}[kind]
    monkeypatch.setattr(access_filters, 'ManagerProvider', provider)
    monkeypatch.setattr(access_filters, 'load_grants', lambda _user: state['grants'])

    return state


class TestDeniedTypeIds:
    """denied_types + denied_type_ids"""

    def test_a_finite_denial_reads_no_type(self, engine: dict[str, Any]) -> None:
        """Routers, without a Type or object read"""
        assert denied_types(USER, VIEW) == DeniedTypes(ids=frozenset({ROUTER_TYPE_ID}))
        assert denied_type_ids(USER, VIEW) == [ROUTER_TYPE_ID]
        engine['types'].get_all_type_ids.assert_not_called()
        engine['objects'].get_distinct.assert_not_called()

    def test_a_complement_lists_every_type_id_but_the_admitted_gone_ones_too(self, engine: dict[str, Any]) -> None:
        """The existing Types and the ids the objects carry - a gone Type's listed; junk ids passed over"""
        engine['grants'] = COMPLEMENT_GRANTS

        assert denied_type_ids(USER, VIEW) == [ROUTER_TYPE_ID, SWITCH_TYPE_ID, GONE_TYPE_ID]
        engine['types'].get_all_type_ids.assert_called_once_with()
        engine['objects'].get_distinct.assert_called_once_with('type_id', {})


class TestScopeFilter:
    """scope_filter"""

    def test_over_every_type(self, engine: dict[str, Any]) -> None:
        """$nin for a finite denial, $in for a complement"""
        assert scope_filter(USER, VIEW) == {'type_id': {'$nin': [ROUTER_TYPE_ID]}}
        engine['grants'] = COMPLEMENT_GRANTS
        assert scope_filter(USER, VIEW) == {'type_id': {'$in': [SERVER_TYPE_ID]}}

    @pytest.mark.usefixtures('engine')
    def test_for_one_type(self) -> None:
        """An allowed Type needs no filter; a denied one matches no object"""
        assert not scope_filter(USER, VIEW, SERVER_TYPE_ID)
        assert scope_filter(USER, VIEW, ROUTER_TYPE_ID) == {'type_id': {'$in': []}}
        assert scope_filter(USER, [VIEW, EDIT], SERVER_TYPE_ID) == {'type_id': {'$in': []}}


@pytest.mark.usefixtures('engine')
class TestTypeAnswers:
    """permitted_types_criteria, type_allows, operations_on_types"""

    def test_permitted_types_criteria(self) -> None:
        """The Types collection's own key"""
        assert permitted_types_criteria(USER, VIEW) == {'public_id': {'$nin': [ROUTER_TYPE_ID]}}

    def test_type_allows(self) -> None:
        """Servers yes, routers no, the free switch yes; several operations all held"""
        assert type_allows(USER, VIEW, SERVER_TYPE_ID)
        assert not type_allows(USER, VIEW, ROUTER_TYPE_ID)
        assert type_allows(USER, [VIEW, EDIT], SWITCH_TYPE_ID)
        assert not type_allows(USER, [VIEW, EDIT], SERVER_TYPE_ID)

    def test_operations_on_types(self) -> None:
        """Per Type, in enum order"""
        expected: dict[int, list[ScopeOperation]] = {SERVER_TYPE_ID: [VIEW], ROUTER_TYPE_ID: []}

        assert operations_on_types(USER, [SERVER_TYPE_ID, ROUTER_TYPE_ID]) == expected

    def test_allowed_operation_values(self) -> None:
        """The answer form: the operation values per Type"""
        assert allowed_operation_values(USER, [SERVER_TYPE_ID, SWITCH_TYPE_ID]) == {
            SERVER_TYPE_ID: ['view'], SWITCH_TYPE_ID: ['view', 'create', 'edit', 'delete']}
