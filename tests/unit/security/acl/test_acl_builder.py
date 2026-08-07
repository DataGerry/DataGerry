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
Unit tests for the access-control pipeline filter

The filter resolves the CmdbTypes a group may NOT access and excludes their type_ids from the object
pipeline. The criteria builder and the stage builder are pure; only the resolver touches a manager,
and it is driven here through a stubbed ManagerProvider.
"""
from types import SimpleNamespace
from typing import Any

import pytest

from cmdb.security.acl.builder import (
    DENIED_TYPES_PROJECTION,
    build_acl_pipeline,
    build_acl_stages,
    build_denied_types_criteria,
    build_group_permissions_path,
    resolve_denied_type_ids,
)
from cmdb.security.acl.permission import AccessControlPermission
# -------------------------------------------------------------------------------------------------------------------- #

# "no stages at all" is the contract for an unrestricted group, so these assert the exact empty list
# rather than falsiness - a None slipping through would break every caller that splices the result
# pylint: disable=use-implicit-booleaness-not-comparison

GROUP_ID: int = 7
DENIED_TYPE_IDS: list[int] = [3, 9]
TYPE_ID_KEY: str = 'type_id'
PUBLIC_ID_KEY: str = 'public_id'


class _StubTypesManager:
    """Stand-in for TypesManager recording the find() call the resolver makes."""

    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.documents = documents
        self.calls: list[dict[str, Any]] = []

    def find(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Mirrors BaseManager.find, recording its keyword arguments."""
        self.calls.append(kwargs)
        return self.documents


@pytest.fixture(name='user')
def fixture_user() -> SimpleNamespace:
    """A minimal user stub exposing only the group_id the filter reads."""
    return SimpleNamespace(group_id=GROUP_ID)


def _stub_types_manager(monkeypatch: pytest.MonkeyPatch, manager: _StubTypesManager) -> None:
    """Routes ManagerProvider.get_manager to the given stub."""
    monkeypatch.setattr(
        'cmdb.manager.manager_provider_model.ManagerProvider.get_manager',
        lambda *_a, **_k: manager,
    )


# -------------------------------------------------------------------------------------------------------------------- #
#                                          build_group_permissions_path                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildGroupPermissionsPath:
    """The dotted path addressing one group's permission list inside a stored type's ACL."""

    def test_path_shape(self) -> None:
        """The path walks acl -> groups -> includes -> <group_id>."""
        assert build_group_permissions_path(GROUP_ID) == f'acl.groups.includes.{GROUP_ID}'

    def test_group_id_is_interpolated(self) -> None:
        """A different group addresses a different key."""
        assert build_group_permissions_path(1).endswith('.1')


# -------------------------------------------------------------------------------------------------------------------- #
#                                           build_denied_types_criteria                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildDeniedTypesCriteria:
    """The framework.types filter selecting the types a group may not access."""

    @staticmethod
    def _clauses() -> list[dict[str, Any]]:
        """The three $and clauses of the criteria."""
        return build_denied_types_criteria(GROUP_ID, AccessControlPermission.READ)['$and']

    def test_requires_an_acl_to_be_present(self) -> None:
        """A type with no ACL at all can never be denied."""
        assert {'acl': {'$exists': True}} in self._clauses()

    def test_excludes_a_deactivated_acl(self) -> None:
        """An ACL switched off denies nothing; `$ne` also covers an ACL with no activated key."""
        assert {'acl.activated': {'$ne': False}} in self._clauses()

    def test_negates_the_permission_check(self) -> None:
        """The group is denied unless its list carries the permission, via $nor over $all."""
        expected = {'$nor': [{f'acl.groups.includes.{GROUP_ID}': {'$all': ['READ']}}]}

        assert expected in self._clauses()

    def test_uses_the_permission_string_value(self) -> None:
        """A stored ACL holds permission strings, so the query must compare against .value."""
        criteria = build_denied_types_criteria(GROUP_ID, AccessControlPermission.UPDATE)

        assert criteria['$and'][2]['$nor'][0][f'acl.groups.includes.{GROUP_ID}'] == {'$all': ['UPDATE']}

    @pytest.mark.parametrize('permission', list(AccessControlPermission))
    def test_every_permission_builds_a_criteria(self, permission: AccessControlPermission) -> None:
        """Each of the four permissions produces a well-formed three-clause criteria."""
        assert len(build_denied_types_criteria(GROUP_ID, permission)['$and']) == 3


# -------------------------------------------------------------------------------------------------------------------- #
#                                                build_acl_stages                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildAclStages:
    """The pipeline stages excluding the denied types."""

    def test_no_denied_types_yields_no_stages(self) -> None:
        """A group that may access everything costs nothing - the query runs unfiltered."""
        assert build_acl_stages([]) == []

    def test_denied_types_yield_one_match_stage(self) -> None:
        """A single $match excludes the denied type_ids."""
        assert build_acl_stages(DENIED_TYPE_IDS) == [{'$match': {TYPE_ID_KEY: {'$nin': DENIED_TYPE_IDS}}}]

    def test_the_filter_is_an_exclusion(self) -> None:
        """$nin, not $in - so an object whose type_id matches no CmdbType still passes."""
        stage = build_acl_stages(DENIED_TYPE_IDS)[0]['$match'][TYPE_ID_KEY]

        assert '$nin' in stage and '$in' not in stage


# -------------------------------------------------------------------------------------------------------------------- #
#                                            resolve_denied_type_ids                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestResolveDeniedTypeIds:
    """The one projected query the filter runs against framework.types."""

    def test_returns_the_public_ids(self, user: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
        """Each denied type document contributes its public_id."""
        _stub_types_manager(monkeypatch, _StubTypesManager([{PUBLIC_ID_KEY: 3}, {PUBLIC_ID_KEY: 9}]))

        assert resolve_denied_type_ids(user, AccessControlPermission.READ) == DENIED_TYPE_IDS

    def test_no_denied_types_yields_an_empty_list(
        self, user: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Nothing denied is the common case and must not raise."""
        _stub_types_manager(monkeypatch, _StubTypesManager([]))

        assert resolve_denied_type_ids(user, AccessControlPermission.READ) == []

    def test_a_document_without_a_public_id_is_skipped(
        self, user: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A malformed type document cannot inject a None into the $nin list."""
        _stub_types_manager(monkeypatch, _StubTypesManager([{PUBLIC_ID_KEY: 3}, {'name': 'broken'}]))

        assert resolve_denied_type_ids(user, AccessControlPermission.READ) == [3]

    def test_only_the_identity_is_projected(
        self, user: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The resolver never loads whole type documents."""
        manager = _StubTypesManager([])
        _stub_types_manager(monkeypatch, manager)

        resolve_denied_type_ids(user, AccessControlPermission.READ)

        assert manager.calls[0]['projection'] == DENIED_TYPES_PROJECTION

    def test_the_criteria_is_the_denied_types_filter(
        self, user: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The resolver queries with exactly the criteria the pure builder produces."""
        manager = _StubTypesManager([])
        _stub_types_manager(monkeypatch, manager)

        resolve_denied_type_ids(user, AccessControlPermission.READ)

        assert manager.calls[0]['criteria'] == build_denied_types_criteria(GROUP_ID, AccessControlPermission.READ)

    def test_a_string_group_id_is_coerced(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """group_id arrives as an int in the path even when the user carries it as a string."""
        manager = _StubTypesManager([])
        _stub_types_manager(monkeypatch, manager)

        resolve_denied_type_ids(SimpleNamespace(group_id='7'), AccessControlPermission.READ)

        assert f'acl.groups.includes.{GROUP_ID}' in str(manager.calls[0]['criteria'])

    def test_runs_exactly_one_query(self, user: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
        """The join this replaced ran per document; the replacement runs once."""
        manager = _StubTypesManager([])
        _stub_types_manager(monkeypatch, manager)

        resolve_denied_type_ids(user, AccessControlPermission.READ)

        assert len(manager.calls) == 1


# -------------------------------------------------------------------------------------------------------------------- #
#                                              build_acl_pipeline                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildAclPipeline:
    """The public entry point: resolve, then build."""

    def test_denied_types_produce_the_match(self, user: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
        """A denied type ends up excluded from the object pipeline."""
        _stub_types_manager(monkeypatch, _StubTypesManager([{PUBLIC_ID_KEY: 3}, {PUBLIC_ID_KEY: 9}]))

        pipeline = build_acl_pipeline(user, AccessControlPermission.READ)

        assert pipeline == [{'$match': {TYPE_ID_KEY: {'$nin': DENIED_TYPE_IDS}}}]

    def test_nothing_denied_produces_no_stages(
        self, user: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The unrestricted case adds no stage to the pipeline at all."""
        _stub_types_manager(monkeypatch, _StubTypesManager([]))

        assert build_acl_pipeline(user, AccessControlPermission.READ) == []

    def test_no_lookup_stage_is_emitted(self, user: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
        """Regression: the filter used to $lookup framework.types for every single document."""
        _stub_types_manager(monkeypatch, _StubTypesManager([{PUBLIC_ID_KEY: 3}]))

        pipeline = build_acl_pipeline(user, AccessControlPermission.READ)

        assert not [stage for stage in pipeline if '$lookup' in stage or '$unwind' in stage]

    def test_only_filter_stages_are_emitted(
        self, user: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression: the old $lookup/$unwind attached a whole CmdbType to every document, so the
        filter must contribute nothing but $match stages - it may not reshape what flows through."""
        _stub_types_manager(monkeypatch, _StubTypesManager([{PUBLIC_ID_KEY: 3}]))

        pipeline = build_acl_pipeline(user, AccessControlPermission.READ)

        assert {stage_op for stage in pipeline for stage_op in stage} == {'$match'}
