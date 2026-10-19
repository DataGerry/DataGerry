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
Unit tests for cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_change_guard_helper

Covers what an update or a delete of a CmdbType may not do while CmdbObjects depend on it: the location-field
removal, selectable_as_parent and uses_ports guards with their usage payloads, the field and multi-data-section
identifier guards, and the delete guard with its object count. DB-touching collaborators are patched at the module
path; CmdbTypes are lightweight SimpleNamespace stand-ins exposing only the attributes the helpers read. Schema dict
keys are referenced via the model key enums
"""
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.models.type_model import FieldKey, FieldType, TypeSchemaKey
from cmdb.models.object_model import CmdbObjectKey, CmdbObjectFieldKey
from cmdb.errors.manager.objects_manager import ObjectsManagerGetError
from cmdb.manager.manager_provider_model import ManagerType
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types import types_change_guard_helper, types_helper
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_constants import UsesPortsUsageKey
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_change_guard_helper import (
    describe_identifier_swap,
    field_identifier_change_blocker,
    guard_field_identifier_change,
    guard_mds_section_identifier_change,
    mds_section_identifier_change_blocker,
    type_has_objects,
    guard_location_field_removal,
    guard_selectable_as_parent_change,
    location_field_removal_blocker,
    selectable_as_parent_change_blocker,
    build_location_usage_payload,
    verify_type_deletable,
    count_objects_of_type,
    get_objects_using_location_field,
    get_port_usage_of_type,
    build_uses_ports_usage_payload,
    uses_ports_change_blocker,
    guard_uses_ports_change,
)
# -------------------------------------------------------------------------------------------------------------------- #

PATH: str = 'cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_change_guard_helper'

HTTP_BAD_REQUEST: int = 400
HTTP_NOT_FOUND: int = 404


# Everything the module offers its callers - the routes and the type importer's rules
GUARD_HELPER_API: frozenset[str] = frozenset({
    'get_objects_using_location_field', 'build_location_usage_payload', 'get_port_usage_of_type',
    'build_uses_ports_usage_payload', 'uses_ports_change_blocker', 'guard_uses_ports_change',
    'selectable_as_parent_change_blocker', 'guard_selectable_as_parent_change', 'count_objects_of_type',
    'verify_type_deletable', 'location_field_removal_blocker', 'guard_location_field_removal', 'type_has_objects',
    'describe_identifier_swap', 'field_identifier_change_blocker', 'guard_field_identifier_change',
    'mds_section_identifier_change_blocker', 'guard_mds_section_identifier_change',
})


# ------------------------------------------------------- the module's place ----------------------------------------- #

def test_the_module_defines_exactly_its_listed_functions() -> None:
    """Nothing a caller imports went missing, nothing new appeared unnoticed"""
    defined: set[str] = {
        name for name, member in vars(types_change_guard_helper).items()
        if callable(member) and getattr(member, '__module__', None) == types_change_guard_helper.__name__
    }

    assert defined == GUARD_HELPER_API


@pytest.mark.parametrize('name', sorted(GUARD_HELPER_API))
def test_types_helper_does_not_offer_it_too(name: str) -> None:
    """
    No second spelling: a re-export would let a test patch the name in types_helper and silently miss the guard
    module's own reference
    """
    assert not hasattr(types_helper, name)


def test_types_helper_does_not_import_the_guard_module() -> None:
    """The guard module reads get_location_field from types_helper, so the reverse import would be a cycle"""
    assert not any(member is types_change_guard_helper for member in vars(types_helper).values())


def _type_with_location(has_location: bool) -> SimpleNamespace:
    """Builds a CmdbType stand-in whose get_fields() includes a location field when requested."""
    fields: list[dict[str, Any]] = [{FieldKey.NAME.value: 'text-a', FieldKey.TYPE.value: FieldType.TEXT.value}]

    if has_location:
        fields.append({FieldKey.NAME.value: 'loc', FieldKey.TYPE.value: FieldType.LOCATION.value})

    return SimpleNamespace(get_fields=lambda: fields)


# ------------------------------------------------- guard_location_field_removal ------------------------------------- #

def test_guard_location_field_removal_noop_when_field_kept() -> None:
    """No usage lookup runs when the location field is not being removed."""
    old_type = _type_with_location(True)
    new_type = _type_with_location(True)

    with patch(f'{PATH}.get_objects_using_location_field') as mock_usage:
        guard_location_field_removal(MagicMock(), old_type, new_type)

    mock_usage.assert_not_called()


def test_guard_location_field_removal_aborts_when_objects_still_use_it() -> None:
    """Removing the location field while objects still hold a value aborts 400."""
    old_type = _type_with_location(True)
    new_type = _type_with_location(False)

    with patch(f'{PATH}.get_objects_using_location_field', return_value=[1, 2]):
        with pytest.raises(HTTPException) as exc_info:
            guard_location_field_removal(MagicMock(), old_type, new_type)

    assert exc_info.value.code == HTTP_BAD_REQUEST


def test_guard_location_field_removal_allows_when_no_objects_use_it() -> None:
    """Removing the location field is allowed when no object holds a value."""
    old_type = _type_with_location(True)
    new_type = _type_with_location(False)

    with patch(f'{PATH}.get_objects_using_location_field', return_value=[]):
        guard_location_field_removal(MagicMock(), old_type, new_type)  # must not raise


def test_location_field_removal_blocker_reports_the_reason() -> None:
    """The blocker hands the reason back instead of aborting, so the type import can report it."""
    with patch(f'{PATH}.get_objects_using_location_field', return_value=[1, 2]):
        blocker = location_field_removal_blocker(
            MagicMock(), _type_with_location(True), _type_with_location(False),
        )

    assert blocker is not None
    assert '2 Object(s)' in blocker


def test_location_field_removal_blocker_is_none_when_allowed() -> None:
    """No reason means the removal is allowed - what the route turns into 'do not abort'."""
    with patch(f'{PATH}.get_objects_using_location_field', return_value=[]):
        assert location_field_removal_blocker(
            MagicMock(), _type_with_location(True), _type_with_location(False),
        ) is None


# ------------------------------------------------- guard_selectable_as_parent_change -------------------------------- #

def _type_selectable(value: bool) -> SimpleNamespace:
    """Builds a CmdbType stand-in carrying only the selectable_as_parent flag the guard reads."""
    return SimpleNamespace(selectable_as_parent=value)


@pytest.mark.parametrize('old_value, new_value', [(True, True), (False, True), (False, False)])
def test_guard_selectable_as_parent_change_noop_unless_turning_off(old_value: bool, new_value: bool) -> None:
    """No usage lookup runs unless the flag transitions true -> false."""
    with patch(f'{PATH}.get_objects_using_location_field') as mock_usage:
        guard_selectable_as_parent_change(MagicMock(), _type_selectable(old_value), _type_selectable(new_value))

    mock_usage.assert_not_called()


def test_guard_selectable_as_parent_change_aborts_when_objects_placed() -> None:
    """Turning selectable_as_parent off while objects of the type are placed aborts 400."""
    with patch(f'{PATH}.get_objects_using_location_field', return_value=[1, 2]):
        with pytest.raises(HTTPException) as exc_info:
            guard_selectable_as_parent_change(MagicMock(), _type_selectable(True), _type_selectable(False))

    assert exc_info.value.code == HTTP_BAD_REQUEST


def test_guard_selectable_as_parent_change_allows_when_no_objects_placed() -> None:
    """Turning selectable_as_parent off is allowed when no object of the type is placed."""
    with patch(f'{PATH}.get_objects_using_location_field', return_value=[]):
        guard_selectable_as_parent_change(MagicMock(), _type_selectable(True), _type_selectable(False))  # no raise


def test_selectable_as_parent_change_blocker_reports_the_reason() -> None:
    """The blocker hands the reason back instead of aborting, so the type import can report it."""
    with patch(f'{PATH}.get_objects_using_location_field', return_value=[1, 2, 3]):
        blocker = selectable_as_parent_change_blocker(
            MagicMock(), _type_selectable(True), _type_selectable(False),
        )

    assert blocker is not None
    assert '3 Object(s)' in blocker


def test_selectable_as_parent_change_blocker_is_none_when_allowed() -> None:
    """No reason means the change is allowed - what the route turns into 'do not abort'."""
    with patch(f'{PATH}.get_objects_using_location_field', return_value=[]):
        assert selectable_as_parent_change_blocker(
            MagicMock(), _type_selectable(True), _type_selectable(False),
        ) is None


# ------------------------------------------------- build_location_usage_payload ------------------------------------- #

def test_build_location_usage_payload_reports_not_in_use_when_empty() -> None:
    """With no placed objects the payload reports in_use False, count 0, empty id list."""
    with patch(f'{PATH}.get_objects_using_location_field', return_value=[]):
        payload = build_location_usage_payload(MagicMock(), SimpleNamespace())

    assert payload == {'in_use': False, 'count': 0, 'object_public_ids': []}


def test_build_location_usage_payload_reports_in_use_with_ids() -> None:
    """With placed objects the payload reports in_use True, the count, and the ids."""
    with patch(f'{PATH}.get_objects_using_location_field', return_value=[7, 8, 9]):
        payload = build_location_usage_payload(MagicMock(), SimpleNamespace())

    assert payload == {'in_use': True, 'count': 3, 'object_public_ids': [7, 8, 9]}


# ------------------------------------------------------ verify_type_deletable --------------------------------------- #

def _patch_managers_by_type(managers: dict) -> Any:
    """Patches ManagerProvider.get_manager to return the mock registered for each ManagerType."""
    return patch(f'{PATH}.ManagerProvider.get_manager', side_effect=lambda mtype, _user: managers[mtype])


def _types_manager(found: list[dict[str, Any]] | None = None) -> MagicMock:
    """A TypesManager stand-in whose find() returns the given dependents."""
    manager = MagicMock()
    manager.find.return_value = found or []

    return manager


def _dependent(public_id: int = 901, name: str = 'test', label: str | None = 'test') -> dict[str, Any]:
    """One dependent type as the projected ref-section lookup returns it."""
    return {
        TypeSchemaKey.PUBLIC_ID.value: public_id,
        TypeSchemaKey.NAME.value: name,
        TypeSchemaKey.LABEL.value: label,
    }


def test_count_objects_of_type_counts_every_object_of_the_type() -> None:
    """One filter - the type id - with no active flag and no ACL narrowing"""
    objects = MagicMock()
    objects.count_documents.return_value = 4

    assert count_objects_of_type(objects, 7) == 4
    objects.count_documents.assert_called_once_with({CmdbObjectKey.TYPE_ID: 7})


def test_count_objects_of_type_lets_the_read_error_through() -> None:
    """The caller maps the failure - the route to 400, the delete to 400"""
    objects = MagicMock()
    objects.count_documents.side_effect = ObjectsManagerGetError('down')

    with pytest.raises(ObjectsManagerGetError):
        count_objects_of_type(objects, 7)


def test_verify_type_deletable_refuses_on_the_shared_count() -> None:
    """The guard asks count_objects_of_type - the same question as the pre-check route"""
    objects = MagicMock()

    with _patch_managers_by_type({ManagerType.OBJECTS: objects, ManagerType.REPORTS: MagicMock(),
                                  ManagerType.TYPES: _types_manager()}), \
            patch(f'{PATH}.count_objects_of_type', return_value=1) as count, \
            pytest.raises(HTTPException) as exc_info:
        verify_type_deletable(MagicMock(), 1, {TypeSchemaKey.PUBLIC_ID.value: 1})

    count.assert_called_once_with(objects, 1)
    assert exc_info.value.code == HTTP_BAD_REQUEST


def test_verify_type_deletable_aborts_404_when_type_missing() -> None:
    """A missing type (to_delete_type None) aborts 404."""
    with patch(f'{PATH}.ManagerProvider.get_manager', return_value=MagicMock()):
        with pytest.raises(HTTPException) as exc_info:
            verify_type_deletable(MagicMock(), 1, None)

    assert exc_info.value.code == HTTP_NOT_FOUND


def test_verify_type_deletable_aborts_400_when_objects_exist() -> None:
    """A type that still has objects cannot be deleted (400)."""
    objects = MagicMock()
    objects.count_documents.return_value = 3
    reports = MagicMock()
    reports.count_documents.return_value = 0

    with _patch_managers_by_type({ManagerType.OBJECTS: objects, ManagerType.REPORTS: reports,
                                  ManagerType.TYPES: _types_manager()}):
        with pytest.raises(HTTPException) as exc_info:
            verify_type_deletable(MagicMock(), 1, {TypeSchemaKey.PUBLIC_ID.value: 1})

    assert exc_info.value.code == HTTP_BAD_REQUEST


def test_verify_type_deletable_aborts_400_when_reports_use_it() -> None:
    """A type still referenced by reports cannot be deleted (400)."""
    objects = MagicMock()
    objects.count_documents.return_value = 0
    reports = MagicMock()
    reports.count_documents.return_value = 2

    with _patch_managers_by_type({ManagerType.OBJECTS: objects, ManagerType.REPORTS: reports,
                                  ManagerType.TYPES: _types_manager()}):
        with pytest.raises(HTTPException) as exc_info:
            verify_type_deletable(MagicMock(), 1, {TypeSchemaKey.PUBLIC_ID.value: 1})

    assert exc_info.value.code == HTTP_BAD_REQUEST


def test_verify_type_deletable_passes_when_unused() -> None:
    """No objects and no reports means the type may be deleted (no abort)."""
    objects = MagicMock()
    objects.count_documents.return_value = 0
    reports = MagicMock()
    reports.count_documents.return_value = 0

    with _patch_managers_by_type({ManagerType.OBJECTS: objects, ManagerType.REPORTS: reports,
                                  ManagerType.TYPES: _types_manager()}):
        verify_type_deletable(MagicMock(), 1, {TypeSchemaKey.PUBLIC_ID.value: 1})  # must not raise


def test_verify_type_deletable_aborts_400_when_a_ref_section_points_at_it() -> None:
    """
    A type another type pulls fields from cannot be deleted (400)

    Deleting it leaves the dependent's ref-section pointing at a type_id that no longer resolves,
    which is the type-level half of the referenced-section removal guard.
    """
    objects = MagicMock()
    objects.count_documents.return_value = 0
    reports = MagicMock()
    reports.count_documents.return_value = 0

    with _patch_managers_by_type({ManagerType.OBJECTS: objects, ManagerType.REPORTS: reports,
                                  ManagerType.TYPES: _types_manager([_dependent()])}):
        with pytest.raises(HTTPException) as exc_info:
            verify_type_deletable(MagicMock(), 1, {TypeSchemaKey.PUBLIC_ID.value: 1})

    assert exc_info.value.code == HTTP_BAD_REQUEST
    assert 'test' in exc_info.value.description


def test_verify_type_deletable_ignores_a_self_reference() -> None:
    """A type whose OWN ref-section points at itself is not blocked by it - it goes away with it"""
    objects = MagicMock()
    objects.count_documents.return_value = 0
    reports = MagicMock()
    reports.count_documents.return_value = 0
    types = _types_manager()

    with _patch_managers_by_type({ManagerType.OBJECTS: objects, ManagerType.REPORTS: reports,
                                  ManagerType.TYPES: types}):
        verify_type_deletable(MagicMock(), 1, {TypeSchemaKey.PUBLIC_ID.value: 1})  # must not raise

    assert types.find.call_args.kwargs['criteria'][TypeSchemaKey.PUBLIC_ID.value] == {'$ne': 1}


# ------------------------------------------------- get_objects_using_location_field --------------------------------- #

def test_get_objects_using_location_field_returns_empty_without_location_field() -> None:
    """A type with no location field returns [] and never queries objects."""
    target_type = SimpleNamespace(get_fields=lambda: [{FieldKey.TYPE.value: FieldType.TEXT.value}])

    with patch(f'{PATH}.ManagerProvider.get_manager') as provider:
        assert get_objects_using_location_field(MagicMock(), target_type) == []

    provider.assert_not_called()


def test_get_objects_using_location_field_queries_and_returns_public_ids() -> None:
    """With a location field, the $elemMatch query runs and matching object public_ids are returned."""
    target_type = SimpleNamespace(
        get_fields=lambda: [{FieldKey.NAME.value: 'loc', FieldKey.TYPE.value: FieldType.LOCATION.value}],
        get_public_id=lambda: 5,
    )
    objects = MagicMock()
    objects.find_objects.return_value = [{CmdbObjectKey.PUBLIC_ID.value: 1}, {CmdbObjectKey.PUBLIC_ID.value: 2}]

    with patch(f'{PATH}.ManagerProvider.get_manager', return_value=objects):
        result = get_objects_using_location_field(MagicMock(), target_type)

    assert result == [1, 2]
    criteria = objects.find_objects.call_args.args[0]
    assert criteria[CmdbObjectKey.TYPE_ID] == 5
    elem_match = criteria[CmdbObjectKey.FIELDS]['$elemMatch']
    assert elem_match[CmdbObjectFieldKey.NAME] == 'loc'
    assert elem_match[CmdbObjectFieldKey.VALUE] == {'$gt': 0}


# ---------------------------------------------- uses_ports true -> false -------------------------------------------- #

PORT_TYPE_ID: int = 950
OWNER_ID: int = 960
OTHER_OWNER_ID: int = 961


def _uses_ports_type(uses_ports: bool, public_id: int = PORT_TYPE_ID) -> SimpleNamespace:
    """A CmdbType stand-in exposing only what the uses_ports guard reads."""
    return SimpleNamespace(uses_ports=uses_ports, get_public_id=lambda: public_id)


def _objects_manager_with(object_ids: list[int]) -> MagicMock:
    """An ObjectsManager whose projected find returns the given object public_ids."""
    manager = MagicMock()
    manager.find_objects.return_value = [{CmdbObjectKey.PUBLIC_ID.value: oid} for oid in object_ids]

    return manager


def _ports_manager_with(port_count: int, owners: list[int] | None = None) -> MagicMock:
    """A PortsManager reporting the given port count and distinct owners."""
    manager = MagicMock()
    manager.count_documents.return_value = port_count
    manager.get_distinct.return_value = owners if owners is not None else []

    return manager


def _port_managers(object_ids: list[int], port_count: int, owners: list[int] | None = None) -> dict:
    """The manager mapping the uses_ports helpers resolve."""
    return {
        ManagerType.OBJECTS: _objects_manager_with(object_ids),
        ManagerType.PORTS: _ports_manager_with(port_count, owners),
    }


class TestGetPortUsageOfType:
    """Counting the ports of a Type's objects."""

    def test_reports_both_counts(self) -> None:
        """The refusal message names ports AND objects, so both are resolved in one pass"""
        managers = _port_managers([OWNER_ID, OTHER_OWNER_ID], port_count=5, owners=[OWNER_ID])

        with _patch_managers_by_type(managers):
            usage = get_port_usage_of_type(MagicMock(), _uses_ports_type(True))

        assert usage[UsesPortsUsageKey.PORT_COUNT.value] == 5
        assert usage[UsesPortsUsageKey.OBJECT_COUNT.value] == 1

    def test_queries_the_ports_of_the_types_objects_only(self) -> None:
        """
        A port stores its owner, not its type, so the filter is an $in over the type's object ids

        A filter that forgot the $in would count every port in the installation.
        """
        managers = _port_managers([OWNER_ID, OTHER_OWNER_ID], port_count=0)

        with _patch_managers_by_type(managers):
            get_port_usage_of_type(MagicMock(), _uses_ports_type(True))

        criteria = managers[ManagerType.PORTS].count_documents.call_args.args[0]
        assert criteria == {'object_id': {'$in': [OWNER_ID, OTHER_OWNER_ID]}}

    def test_reads_only_the_object_public_ids(self) -> None:
        """This runs on a type-edit page load, so whole object documents are never loaded"""
        managers = _port_managers([OWNER_ID], port_count=0)

        with _patch_managers_by_type(managers):
            get_port_usage_of_type(MagicMock(), _uses_ports_type(True))

        kwargs = managers[ManagerType.OBJECTS].find_objects.call_args.kwargs
        assert kwargs['projection'] == {CmdbObjectKey.PUBLIC_ID.value: 1}
        assert kwargs['as_dict'] is True

    def test_a_type_without_objects_costs_no_port_query(self) -> None:
        """
        Short-circuited: an $in over an empty list would match nothing anyway

        Worth the branch because a type with no objects is the common case while a feature is being
        set up.
        """
        managers = _port_managers([], port_count=7)

        with _patch_managers_by_type(managers):
            usage = get_port_usage_of_type(MagicMock(), _uses_ports_type(True))

        assert usage[UsesPortsUsageKey.PORT_COUNT.value] == 0
        managers[ManagerType.PORTS].count_documents.assert_not_called()


class TestBuildUsesPortsUsagePayload:
    """The pre-check payload."""

    def test_reports_in_use_with_the_counts(self) -> None:
        """in_use true means the flag may NOT be cleared"""
        with _patch_managers_by_type(_port_managers([OWNER_ID], 3, [OWNER_ID])):
            payload = build_uses_ports_usage_payload(MagicMock(), _uses_ports_type(True))

        assert payload == {
            UsesPortsUsageKey.IN_USE.value: True,
            UsesPortsUsageKey.PORT_COUNT.value: 3,
            UsesPortsUsageKey.OBJECT_COUNT.value: 1,
        }

    def test_reports_a_free_type(self) -> None:
        """in_use false is the frontend's green light to offer removing the section"""
        with _patch_managers_by_type(_port_managers([OWNER_ID], 0)):
            payload = build_uses_ports_usage_payload(MagicMock(), _uses_ports_type(True))

        assert payload[UsesPortsUsageKey.IN_USE.value] is False

    def test_carries_no_id_list(self) -> None:
        """
        Counts only - the equivalent location payload is unbounded for a large Type

        The type builder needs to know WHETHER it may clear the flag, not which ports stand in the way.
        """
        with _patch_managers_by_type(_port_managers([OWNER_ID], 3, [OWNER_ID])):
            payload = build_uses_ports_usage_payload(MagicMock(), _uses_ports_type(True))

        assert all(not isinstance(value, list) for value in payload.values())


class TestUsesPortsChangeBlocker:
    """Only the true -> false transition is guarded."""

    def test_refuses_turning_the_flag_off_while_ports_exist(self) -> None:
        """Clearing the flag hides the ports panel, so those ports become unreachable"""
        with _patch_managers_by_type(_port_managers([OWNER_ID], 4, [OWNER_ID])):
            blocker = uses_ports_change_blocker(
                MagicMock(), _uses_ports_type(True), _uses_ports_type(False),
            )

        assert blocker is not None
        assert '4 Port(s)' in blocker
        assert '1 Object(s)' in blocker

    def test_allows_turning_the_flag_off_without_ports(self) -> None:
        """Nothing to lose"""
        with _patch_managers_by_type(_port_managers([OWNER_ID], 0)):
            assert uses_ports_change_blocker(
                MagicMock(), _uses_ports_type(True), _uses_ports_type(False),
            ) is None

    def test_allows_turning_the_flag_on(self) -> None:
        """
        The other direction is governed by the license guard, not by this one

        Costing a query here would also be pure waste on the common enable path.
        """
        managers = _port_managers([OWNER_ID], 4, [OWNER_ID])

        with _patch_managers_by_type(managers):
            assert uses_ports_change_blocker(
                MagicMock(), _uses_ports_type(False), _uses_ports_type(True),
            ) is None

        managers[ManagerType.OBJECTS].find_objects.assert_not_called()

    @pytest.mark.parametrize('old_flag, new_flag', [(True, True), (False, False)],
                             ids=['stays-on', 'stays-off'])
    def test_an_unchanged_flag_costs_no_query(self, old_flag: bool, new_flag: bool) -> None:
        """Every type update runs this, so an unrelated edit must not pay for it"""
        managers = _port_managers([OWNER_ID], 4, [OWNER_ID])

        with _patch_managers_by_type(managers):
            assert uses_ports_change_blocker(
                MagicMock(), _uses_ports_type(old_flag), _uses_ports_type(new_flag),
            ) is None

        managers[ManagerType.OBJECTS].find_objects.assert_not_called()

    @pytest.mark.parametrize('old_flag', [None, 0, ''], ids=['none', 'zero', 'empty'])
    def test_a_falsy_stored_flag_is_not_a_transition(self, old_flag: Any) -> None:
        """
        A type written before the flag existed reads as absent, which is not "turning it off"

        updater_20260901 backfills those, but a database that has not run it yet must not be blocked.
        """
        managers = _port_managers([OWNER_ID], 4, [OWNER_ID])

        with _patch_managers_by_type(managers):
            assert uses_ports_change_blocker(
                MagicMock(),
                SimpleNamespace(uses_ports=old_flag, get_public_id=lambda: PORT_TYPE_ID),
                _uses_ports_type(False),
            ) is None

        managers[ManagerType.OBJECTS].find_objects.assert_not_called()


class TestGuardUsesPortsChange:
    """The route-level wrapper."""

    def test_aborts_400_when_refused(self) -> None:
        """400 is the codebase's business-rule rejection"""
        with _patch_managers_by_type(_port_managers([OWNER_ID], 2, [OWNER_ID])):
            with pytest.raises(HTTPException) as exc_info:
                guard_uses_ports_change(MagicMock(), _uses_ports_type(True), _uses_ports_type(False))

        assert exc_info.value.code == HTTP_BAD_REQUEST

    def test_passes_when_allowed(self) -> None:
        """An allowed update must not raise"""
        with _patch_managers_by_type(_port_managers([OWNER_ID], 0)):
            guard_uses_ports_change(MagicMock(), _uses_ports_type(True), _uses_ports_type(False))


# ----------------------------------------------- the identifier guards ---------------------------------------------- #
# A field's `name` and a multi-data-section's `name` ARE their identity - every CmdbObject keys its
# stored values and rows by them, and nothing sits underneath. A rename is therefore indistinguishable
# from one removal plus one addition, which is exactly the shape these refuse.

def _type_with_fields(*names: str, mds_sections: tuple[str, ...] = ()) -> Any:
    """A CmdbType stand-in carrying a flat field list and, optionally, MDS section ids."""
    return SimpleNamespace(
        public_id=77,
        fields=[{FieldKey.NAME: name, FieldKey.TYPE: FieldType.TEXT} for name in names],
        get_mds_section_ids=lambda: set(mds_sections),
    )


class TestDescribeIdentifierSwap:
    """The pure rename detector both guards are built on."""

    def test_a_removal_with_an_addition_is_rename_shaped(self) -> None:
        """The only shape a rename can take, since a field carries no id but its name."""
        assert describe_identifier_swap({'a', 'b'}, {'a', 'c'}) == (['b'], ['c'])

    def test_a_pure_removal_is_not_a_rename(self) -> None:
        """Dropping a field is a supported operation and stays allowed."""
        assert describe_identifier_swap({'a', 'b'}, {'a'}) is None

    def test_a_pure_addition_is_not_a_rename(self) -> None:
        """Adding a field cannot lose anything."""
        assert describe_identifier_swap({'a'}, {'a', 'b'}) is None

    def test_an_unchanged_set_is_not_a_rename(self) -> None:
        """A metadata-only edit - label, regex, order - touches no identifier."""
        assert describe_identifier_swap({'a', 'b'}, {'b', 'a'}) is None

    def test_both_sides_are_reported_sorted(self) -> None:
        """The message names what went and what came, so the caller can see the swap."""
        assert describe_identifier_swap({'a', 'b', 'c'}, {'z', 'y', 'c'}) == (['a', 'b'], ['y', 'z'])


class TestFieldIdentifierChange:
    """Renaming a field identifier - the flat list, which also holds every MDS field definition."""

    def test_a_rename_is_refused_while_objects_exist(self) -> None:
        """The value would be emptied on every Object of the Type."""
        with patch(f'{PATH}.type_has_objects', return_value=True), pytest.raises(HTTPException) as exc:
            guard_field_identifier_change(
                MagicMock(), _type_with_fields('dg-hostname'), _type_with_fields('dg-host-name'),
            )

        assert exc.value.code == HTTP_BAD_REQUEST
        assert 'dg-hostname' in exc.value.description
        assert 'dg-host-name' in exc.value.description

    def test_a_rename_is_allowed_while_the_type_has_no_objects(self) -> None:
        """A Type still being designed carries no values to lose, like every sibling guard."""
        with patch(f'{PATH}.type_has_objects', return_value=False):
            guard_field_identifier_change(
                MagicMock(), _type_with_fields('dg-hostname'), _type_with_fields('dg-host-name'),
            )  # must not raise

    def test_a_pure_removal_is_still_allowed(self) -> None:
        """Dropping a field remains supported - this guard is about renaming, nothing else."""
        with patch(f'{PATH}.type_has_objects', return_value=True):
            guard_field_identifier_change(
                MagicMock(), _type_with_fields('a', 'b'), _type_with_fields('a'),
            )  # must not raise

    def test_a_pure_addition_is_still_allowed(self) -> None:
        """Adding a field loses nothing."""
        with patch(f'{PATH}.type_has_objects', return_value=True):
            guard_field_identifier_change(
                MagicMock(), _type_with_fields('a'), _type_with_fields('a', 'b'),
            )  # must not raise

    def test_the_object_count_is_not_asked_for_an_unchanged_field_set(self) -> None:
        """A metadata-only edit must not cost a count on every Type update."""
        with patch(f'{PATH}.type_has_objects') as mock_count:
            field_identifier_change_blocker(
                MagicMock(), _type_with_fields('a', 'b'), _type_with_fields('a', 'b'),
            )

        mock_count.assert_not_called()

    def test_the_blocker_reports_instead_of_aborting(self) -> None:
        """The type import reports it per entry rather than aborting the whole batch."""
        with patch(f'{PATH}.type_has_objects', return_value=True):
            blocker = field_identifier_change_blocker(
                MagicMock(), _type_with_fields('old'), _type_with_fields('new'),
            )

        assert blocker is not None
        assert 'separate updates' in blocker


class TestMdsSectionIdentifierChange:
    """Renaming a multi-data-section - the most destructive of the three, it drops every row."""

    def test_a_rename_is_refused_while_objects_exist(self) -> None:
        """The MDS propagation matches sections on (type, name), so a rename reads as a removal."""
        old_type = _type_with_fields('a', mds_sections=('dg-rows',))
        new_type = _type_with_fields('a', mds_sections=('dg-rows-renamed',))

        with patch(f'{PATH}.type_has_objects', return_value=True), pytest.raises(HTTPException) as exc:
            guard_mds_section_identifier_change(MagicMock(), old_type, new_type)

        assert exc.value.code == HTTP_BAD_REQUEST
        assert 'dg-rows' in exc.value.description

    def test_a_rename_is_allowed_while_the_type_has_no_objects(self) -> None:
        """No rows exist yet."""
        old_type = _type_with_fields('a', mds_sections=('dg-rows',))
        new_type = _type_with_fields('a', mds_sections=('dg-rows-renamed',))

        with patch(f'{PATH}.type_has_objects', return_value=False):
            guard_mds_section_identifier_change(MagicMock(), old_type, new_type)  # must not raise

    def test_removing_a_section_outright_is_still_allowed(self) -> None:
        """Dropping an MDS section is a supported operation with its own propagation."""
        old_type = _type_with_fields('a', mds_sections=('dg-rows', 'dg-other'))
        new_type = _type_with_fields('a', mds_sections=('dg-rows',))

        with patch(f'{PATH}.type_has_objects', return_value=True):
            guard_mds_section_identifier_change(MagicMock(), old_type, new_type)  # must not raise

    def test_the_blocker_reports_instead_of_aborting(self) -> None:
        """Same two-path shape as every other rule on this route."""
        old_type = _type_with_fields('a', mds_sections=('dg-rows',))
        new_type = _type_with_fields('a', mds_sections=('dg-new',))

        with patch(f'{PATH}.type_has_objects', return_value=True):
            blocker = mds_section_identifier_change_blocker(MagicMock(), old_type, new_type)

        assert blocker is not None
        assert 'rows' in blocker


class TestTypeHasObjects:
    """The shared condition - one count, no documents loaded."""

    def test_it_counts_the_objects_of_the_type(self) -> None:
        """Counted server-side; the guards never load an Object to decide."""
        objects_manager = MagicMock()
        objects_manager.count_documents.return_value = 3

        with patch(f'{PATH}.ManagerProvider.get_manager', return_value=objects_manager):
            assert type_has_objects(MagicMock(), 77) is True

        assert objects_manager.count_documents.call_args.args[0][CmdbObjectKey.TYPE_ID] == 77

    def test_no_objects_is_false(self) -> None:
        """What lets a Type still being designed be reshaped freely."""
        objects_manager = MagicMock()
        objects_manager.count_documents.return_value = 0

        with patch(f'{PATH}.ManagerProvider.get_manager', return_value=objects_manager):
            assert type_has_objects(MagicMock(), 77) is False
