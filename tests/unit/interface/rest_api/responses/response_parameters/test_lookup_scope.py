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
Unit tests for ``lookup_scope``: the type ACL inside a client ``$lookup`` into the objects

Pure tests - the denied-type read is patched. Pinned: which filters join the objects (at any depth), how each
join form is scoped (the ``pipeline`` form, the ``localField`` / ``foreignField`` form, a join nested in a join),
that other stages and other targets are left alone, that nothing is scoped when nothing is denied, that the
caller's filter is never modified, and that an object join without a known user is refused
"""
from copy import deepcopy
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.interface.rest_api.responses.response_parameters.lookup_scope import (
    UNSCOPED_OBJECT_JOIN_MESSAGE,
    filter_joins_objects,
    scope_client_filter_lookups,
    scope_object_lookups,
)
from cmdb.interface.rest_api.responses.response_parameters.response_parameters_constants import OBJECTS_LOOKUP_TARGET
from cmdb.security.acl.permission import AccessControlPermission
# -------------------------------------------------------------------------------------------------------------------- #

PATH: str = 'cmdb.interface.rest_api.responses.response_parameters.lookup_scope'
DENIED: list[int] = [7, 9]
# A collection a server-built criteria may join; the client guard refuses it, the scoping leaves it alone
OTHER_TARGET: str = 'framework.types'
DENIED_MATCH: dict[str, Any] = {'$match': {'type_id': {'$nin': DENIED}}}
OUTER_MATCH: dict[str, Any] = {'$match': {'active': True}}


def _pipeline_join(*inner: dict[str, Any], target: str = OBJECTS_LOOKUP_TARGET) -> dict[str, Any]:
    """A join in the ``pipeline`` form, with the given own stages."""
    return {'$lookup': {'from': target, 'pipeline': list(inner), 'as': 'joined'}}


FIELD_JOIN: dict[str, Any] = {'$lookup': {'from': OBJECTS_LOOKUP_TARGET, 'localField': 'author_id',
                                          'foreignField': 'author_id', 'as': 'joined'}}


class TestFilterJoinsObjects:
    """Whether a filter needs scoping at all."""

    @pytest.mark.parametrize('criteria', [
        pytest.param([_pipeline_join()], id='pipeline form'),
        pytest.param([FIELD_JOIN], id='localField form'),
        pytest.param([_pipeline_join(_pipeline_join(), target=OTHER_TARGET)], id='nested in another join'),
    ])
    def test_a_join_into_the_objects_is_found(self, criteria: list[dict[str, Any]]) -> None:
        """At the top or one join down"""
        assert filter_joins_objects(criteria) is True

    @pytest.mark.parametrize('criteria', [
        pytest.param({'type_id': 1}, id='filter document'),
        pytest.param([OUTER_MATCH], id='no join'),
        pytest.param([_pipeline_join(target=OTHER_TARGET)], id='another target'),
        pytest.param(None, id='no filter'),
        pytest.param(['not-a-stage'], id='not a stage'),
    ])
    def test_anything_else_is_not(self, criteria: Any) -> None:
        """A document filter cannot hold a stage; other targets and non-stages are not object joins"""
        assert filter_joins_objects(criteria) is False


class TestScopeObjectLookups:
    """Each join into the objects opens on the type exclusion."""

    def test_the_pipeline_form_gets_the_exclusion_first(self) -> None:
        """The denied match comes before the client's own stages"""
        scoped = scope_object_lookups([_pipeline_join(OUTER_MATCH)], DENIED)

        assert scoped[0]['$lookup']['pipeline'] == [DENIED_MATCH, OUTER_MATCH]

    def test_the_local_field_form_gets_a_pipeline_holding_the_exclusion(self) -> None:
        """MongoDB 5.0+ runs a pipeline next to localField / foreignField - the two fields are kept"""
        scoped = scope_object_lookups([FIELD_JOIN], DENIED)

        lookup = scoped[0]['$lookup']
        assert lookup['pipeline'] == [DENIED_MATCH]
        assert (lookup['localField'], lookup['foreignField']) == ('author_id', 'author_id')

    def test_a_nested_join_is_scoped_too(self) -> None:
        """A join inside a join's pipeline opens on the exclusion as well - and the outer one keeps its own"""
        scoped = scope_object_lookups([_pipeline_join(_pipeline_join(OUTER_MATCH))], DENIED)

        outer = scoped[0]['$lookup']['pipeline']
        assert outer[0] == DENIED_MATCH
        assert outer[1]['$lookup']['pipeline'] == [DENIED_MATCH, OUTER_MATCH]

    def test_a_join_into_another_collection_keeps_its_own_stages_but_scopes_what_it_nests(self) -> None:
        """A server-built join elsewhere is not narrowed; an object join inside it is"""
        scoped = scope_object_lookups([_pipeline_join(_pipeline_join(), target=OTHER_TARGET)], DENIED)

        other = scoped[0]['$lookup']['pipeline']
        assert other[0]['$lookup']['pipeline'] == [DENIED_MATCH]
        assert len(other) == 1

    def test_other_stages_are_returned_as_they_are(self) -> None:
        """Only joins are rebuilt"""
        assert scope_object_lookups([OUTER_MATCH, _pipeline_join()], DENIED)[0] is OUTER_MATCH

    @pytest.mark.parametrize('criteria', [[_pipeline_join()], {'type_id': 1}])
    def test_nothing_is_scoped_when_nothing_is_denied(self, criteria: Any) -> None:
        """The common case: the very same criteria comes back"""
        assert scope_object_lookups(criteria, []) is criteria

    def test_the_callers_filter_is_never_modified(self) -> None:
        """A new criteria is built - the client's value is what the response echoes"""
        criteria = [_pipeline_join(OUTER_MATCH), FIELD_JOIN]
        original = deepcopy(criteria)

        scope_object_lookups(criteria, DENIED)

        assert criteria == original


class TestScopeClientFilterLookups:
    """The entry point: the denied types are read only for a filter that joins the objects."""

    def test_a_filter_without_an_object_join_reads_nothing(self) -> None:
        """No join, no denied-type read, the same criteria"""
        criteria = [OUTER_MATCH]

        with patch(f'{PATH}.resolve_denied_type_ids') as resolve:
            assert scope_client_filter_lookups(criteria, MagicMock()) is criteria

        resolve.assert_not_called()

    def test_an_object_join_is_scoped_by_the_users_read_denials(self) -> None:
        """READ is the permission a filter is judged by"""
        user = MagicMock()

        with patch(f'{PATH}.resolve_denied_type_ids', return_value=DENIED) as resolve:
            scoped = scope_client_filter_lookups([_pipeline_join()], user)

        resolve.assert_called_once_with(user, AccessControlPermission.READ)
        assert scoped[0]['$lookup']['pipeline'] == [DENIED_MATCH]

    def test_an_object_join_without_a_user_is_refused(self) -> None:
        """Nothing to scope it for - refused rather than run unscoped"""
        with pytest.raises(ValueError, match='known user'):
            scope_client_filter_lookups([_pipeline_join()], None)

        assert 'known user' in UNSCOPED_OBJECT_JOIN_MESSAGE
