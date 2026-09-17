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
Unit tests for the CmdbType route helpers extracted from the update / clean-status routes

Covers the pure / orchestration helpers in types_helper: the location-field removal guard, the
removed-global-template computation + cleanup, the clean-status item builder and the post-update
side-effect orchestrator. DB-touching collaborators are patched at the module path; CmdbTypes are
lightweight SimpleNamespace stand-ins exposing only the attributes the helpers read. Schema dict
keys are referenced via the model key enums per the no-magic-values rule
"""
import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.models.type_model import FieldKey, FieldType, SectionType, TypeSchemaKey
from cmdb.models.type_model.section_key_enum import SectionKey
from cmdb.models.type_model.section_reference_key_enum import SectionReferenceKey
from cmdb.models.object_model import CmdbObjectKey, CmdbObjectFieldKey
from cmdb.manager.manager_provider_model import ManagerType
from cmdb.models.location_model.location_constants import LocationKey
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types import types_helper
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types import types_reference_section_helper
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_constants import (
    TypeOverviewKey,
    TypeUserDataKey,
    ReferencedSectionUsageKey,
    UsesPortsUsageKey,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_helper import (
    describe_identifier_swap,
    field_identifier_change_blocker,
    guard_field_identifier_change,
    guard_mds_section_identifier_change,
    mds_section_identifier_change_blocker,
    type_has_objects,
    get_types_user_data,
    get_type_or_404,
    get_type_instance_or_404,
    guard_location_field_removal,
    guard_selectable_as_parent_change,
    location_field_removal_blocker,
    selectable_as_parent_change_blocker,
    build_location_usage_payload,
    compute_removed_global_templates,
    apply_removed_global_template_cleanup,
    build_types_overview_items,
    realign_type_objects_if_fields_changed,
    apply_type_update_side_effects,
    verify_type_is_unique,
    verify_type_deletable,
    build_category_criteria,
    build_type_criteria,
    prepare_builder_parameters,
    get_objects_using_location_field,
    type_deletion_followup,
    apply_type_changes_to_locations,
    apply_type_changes_to_mds,
    enforce_special_type_license,
    enforce_rack_selectable_as_parent,
    enforce_uses_ports_license,
    get_port_usage_of_type,
    build_uses_ports_usage_payload,
    uses_ports_change_blocker,
    guard_uses_ports_change,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_reference_section_helper import (
    build_referenced_section_usage_payload,
    describe_section_dependents,
    get_own_referenced_section_names,
    get_own_section_references,
    get_removed_section_names,
    get_section_field_names,
    get_section_reference_selections,
    get_types_referencing_section,
    guard_referenced_section_removal,
    referenced_section_field_removal_blocker,
    referenced_section_removal_blocker,
)
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #

PATH: str = 'cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_helper'

HTTP_BAD_REQUEST: int = 400
HTTP_NOT_FOUND: int = 404


def _type_with_location(has_location: bool) -> SimpleNamespace:
    """Builds a CmdbType stand-in whose get_fields() includes a location field when requested."""
    fields: list[dict[str, Any]] = [{FieldKey.NAME.value: 'text-a', FieldKey.TYPE.value: FieldType.TEXT.value}]

    if has_location:
        fields.append({FieldKey.NAME.value: 'loc', FieldKey.TYPE.value: FieldType.LOCATION.value})

    return SimpleNamespace(get_fields=lambda: fields)


# ------------------------------------------ get_type_or_404 / get_type_instance_or_404 ------------------------------ #

def test_get_type_or_404_returns_the_document() -> None:
    """An existing type is returned as the raw document from the dict-mode lookup."""
    types_manager = MagicMock()
    types_manager.get_type.return_value = {TypeSchemaKey.PUBLIC_ID.value: 1}

    assert get_type_or_404(types_manager, 1) == {TypeSchemaKey.PUBLIC_ID.value: 1}
    types_manager.get_type.assert_called_once_with(1)


def test_get_type_instance_or_404_returns_the_instance() -> None:
    """An existing type is returned hydrated from the instance-mode lookup."""
    types_manager = MagicMock()
    types_manager.get_type_instance.return_value = 'hydrated'

    assert get_type_instance_or_404(types_manager, 1) == 'hydrated'
    types_manager.get_type_instance.assert_called_once_with(1)


@pytest.mark.parametrize(
    'helper, manager_method',
    [(get_type_or_404, 'get_type'), (get_type_instance_or_404, 'get_type_instance')],
    ids=['dict', 'instance'],
)
def test_missing_type_aborts_404_in_both_modes(helper: Any, manager_method: str) -> None:
    """Both helpers abort 404 with the same message when the type does not exist."""
    types_manager = MagicMock()
    getattr(types_manager, manager_method).return_value = None

    with pytest.raises(HTTPException) as exc:
        helper(types_manager, 4711)

    assert exc.value.code == 404
    assert '4711' in exc.value.description


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


# ------------------------------------------------- compute_removed_global_templates --------------------------------- #

def test_compute_removed_global_templates_snapshots_present_sections() -> None:
    """Removed templates are the old-minus-incoming set; hints are captured only for present sections."""
    section = SimpleNamespace(type=SectionType.MDS_SECTION.value, get_fields=lambda: ['a', 'b'])
    old_type = SimpleNamespace(
        global_template_ids=['t1', 'gone'],
        get_section=lambda name: section if name == 't1' else None,
    )

    removed_ids, hints = compute_removed_global_templates(old_type, {'t-keep'})

    assert removed_ids == {'t1', 'gone'}
    assert hints == {'t1': (['a', 'b'], SectionType.MDS_SECTION.value)}


# ------------------------------------------------- apply_removed_global_template_cleanup ---------------------------- #

def test_apply_removed_global_template_cleanup_uses_hints_with_fallback() -> None:
    """Each removed template is cleaned with its snapshotted hint, or (None, None) when absent."""
    manager = MagicMock()
    hints: dict[str, tuple[list[str], str]] = {'t1': (['a'], SectionType.MDS_SECTION.value)}

    apply_removed_global_template_cleanup(manager, 42, {'t1', 't2'}, hints)

    manager.cleanup_global_section_from_type.assert_any_call(
        42, 't1', expected_field_names=['a'], expected_section_type=SectionType.MDS_SECTION.value,
    )
    manager.cleanup_global_section_from_type.assert_any_call(
        42, 't2', expected_field_names=None, expected_section_type=None,
    )
    assert manager.cleanup_global_section_from_type.call_count == 2


# ------------------------------------------------- build_types_overview_items --------------------------------------- #

def _type_doc(public_id: int, field_names: list[str]) -> dict[str, Any]:
    """Builds a CmdbType document with the given field names."""
    return {
        TypeSchemaKey.PUBLIC_ID.value: public_id,
        TypeSchemaKey.FIELDS.value: [{FieldKey.NAME.value: name} for name in field_names],
    }


def test_build_types_overview_items_bundles_type_and_user_data() -> None:
    """Each item bundles the type document with a resolved user-data block (no clean status)."""
    items = build_types_overview_items([_type_doc(1, ['a', 'b'])], {})

    assert items[0][TypeOverviewKey.TYPE_DATA][TypeSchemaKey.PUBLIC_ID.value] == 1
    assert isinstance(items[0][TypeOverviewKey.USER_DATA], dict)
    assert 'clean_status' not in items[0]


def test_build_types_overview_items_one_item_per_type() -> None:
    """One overview item is produced per input type, in order."""
    items = build_types_overview_items([_type_doc(1, ['a']), _type_doc(2, ['b'])], {})

    assert [item[TypeOverviewKey.TYPE_DATA][TypeSchemaKey.PUBLIC_ID.value] for item in items] == [1, 2]


# --------------------------------------------- realign_type_objects_if_fields_changed ------------------------------- #

def _type_with_field_names(public_id: int, field_names: list[str]) -> SimpleNamespace:
    """A minimal CmdbType stub exposing .fields (name dicts) and .public_id for the realign gate."""
    return SimpleNamespace(
        public_id=public_id,
        fields=[{FieldKey.NAME.value: name} for name in field_names],
    )


def test_realign_skips_when_field_names_unchanged() -> None:
    """A metadata-only edit (same field names) triggers no object/report reconciliation."""
    old_type = _type_with_field_names(1, ['a', 'b'])
    updated_type = _type_with_field_names(1, ['a', 'b'])

    with patch(f'{PATH}.ManagerProvider.get_manager') as mock_get, \
         patch(f'{PATH}.realign_objects_to_type') as mock_realign, \
         patch(f'{PATH}.clean_type_reports') as mock_reports:
        realign_type_objects_if_fields_changed(MagicMock(), old_type, updated_type)

    mock_get.assert_not_called()
    mock_realign.assert_not_called()
    mock_reports.assert_not_called()


@pytest.mark.parametrize('old_names, new_names', [
    (['a'], ['a', 'b']),        # field added
    (['a', 'b'], ['a']),        # field removed
])
def test_realign_runs_when_field_set_changed(old_names: list[str], new_names: list[str]) -> None:
    """Adding or removing a field name reconciles the type's objects and reports."""
    old_type = _type_with_field_names(1, old_names)
    updated_type = _type_with_field_names(1, new_names)

    with patch(f'{PATH}.ManagerProvider.get_manager'), \
         patch(f'{PATH}.realign_objects_to_type', return_value=set()) as mock_realign, \
         patch(f'{PATH}.clean_type_reports') as mock_reports:
        realign_type_objects_if_fields_changed(MagicMock(), old_type, updated_type)

    mock_realign.assert_called_once()
    mock_reports.assert_called_once()


# ------------------------------------------------- apply_type_update_side_effects ----------------------------------- #

def test_apply_type_update_side_effects_skips_special_wiring_without_marker() -> None:
    """A non-special type runs cleanup + location/MDS/field-realign propagation but no special wiring."""
    updated_type = SimpleNamespace(public_id=7, special_type=None)

    with patch(f'{PATH}.ManagerProvider.get_manager'), \
         patch(f'{PATH}.apply_removed_global_template_cleanup') as mock_cleanup, \
         patch(f'{PATH}.handle_special_types') as mock_special, \
         patch(f'{PATH}.apply_type_changes_to_locations') as mock_locations, \
         patch(f'{PATH}.apply_type_changes_to_mds') as mock_mds, \
         patch(f'{PATH}.realign_type_objects_if_fields_changed') as mock_realign, \
         patch.object(types_helper.CmdbType, 'to_json', return_value={}):
        apply_type_update_side_effects(MagicMock(), MagicMock(), MagicMock(), updated_type, (set(), {}))

    mock_cleanup.assert_called_once()
    mock_locations.assert_called_once()
    mock_mds.assert_called_once()
    mock_realign.assert_called_once()
    mock_special.assert_not_called()


def test_apply_type_update_side_effects_runs_special_wiring_with_marker() -> None:
    """A special type additionally runs the special-type ref_types wiring."""
    updated_type = SimpleNamespace(public_id=7, special_type='SUBNET')

    with patch(f'{PATH}.ManagerProvider.get_manager'), \
         patch(f'{PATH}.apply_removed_global_template_cleanup'), \
         patch(f'{PATH}.handle_special_types') as mock_special, \
         patch(f'{PATH}.apply_type_changes_to_locations'), \
         patch(f'{PATH}.apply_type_changes_to_mds'), \
         patch(f'{PATH}.realign_type_objects_if_fields_changed'), \
         patch.object(types_helper.CmdbType, 'to_json', return_value={}):
        apply_type_update_side_effects(MagicMock(), MagicMock(), MagicMock(), updated_type, (set(), {}))

    mock_special.assert_called_once()


# --------------------------------------------------- apply_type_changes_to_mds -------------------------------------- #

def _mds_managers(batches: list[list[Any]]) -> tuple[MagicMock, MagicMock]:
    """Builds the two managers the MDS propagation uses, with the propagation yielding the batches."""
    objects_manager = MagicMock(name='objects_manager')
    types_manager = MagicMock(name='types_manager')
    types_manager.handle_multi_data_sections.return_value = iter(batches)

    def _provider(manager_type: ManagerType, _request_user: Any) -> MagicMock:
        return objects_manager if manager_type == ManagerType.OBJECTS else types_manager

    return objects_manager, types_manager, _provider


def test_apply_type_changes_to_mds_writes_every_batch() -> None:
    """
    Each batch is written before the next is read

    The propagation yields rather than collecting, which is what keeps a type with many objects from
    becoming one unbounded read and one unbounded bulk write - so the caller has to loop.
    """
    first_batch = [MagicMock(name='object-1')]
    second_batch = [MagicMock(name='object-2')]
    objects_manager, _types_manager, provider = _mds_managers([first_batch, second_batch])

    with patch(f'{PATH}.ManagerProvider.get_manager', side_effect=provider):
        apply_type_changes_to_mds(MagicMock(), MagicMock(), {})

    assert [call.args[0] for call in objects_manager.bulk_update_multi_data_sections.call_args_list] == [
        first_batch, second_batch,
    ]


def test_apply_type_changes_to_mds_writes_nothing_without_changes() -> None:
    """A propagation that yields nothing performs no write at all"""
    objects_manager, _types_manager, provider = _mds_managers([])

    with patch(f'{PATH}.ManagerProvider.get_manager', side_effect=provider):
        apply_type_changes_to_mds(MagicMock(), MagicMock(), {})

    objects_manager.bulk_update_multi_data_sections.assert_not_called()


# ------------------------------------------------------ verify_type_is_unique --------------------------------------- #

def test_verify_type_is_unique_rejects_existing_public_id() -> None:
    """A pre-assigned public_id that already exists aborts 400."""
    mgr = MagicMock()
    mgr.get_type.return_value = {TypeSchemaKey.PUBLIC_ID.value: 5}

    with pytest.raises(HTTPException) as exc_info:
        verify_type_is_unique(mgr, 'name', public_id=5)

    assert exc_info.value.code == HTTP_BAD_REQUEST


def test_verify_type_is_unique_rejects_duplicate_name() -> None:
    """A name already used by another type aborts 400."""
    mgr = MagicMock()
    mgr.get_one_by.return_value = {TypeSchemaKey.NAME.value: 'name'}

    with pytest.raises(HTTPException) as exc_info:
        verify_type_is_unique(mgr, 'name')

    assert exc_info.value.code == HTTP_BAD_REQUEST


def test_verify_type_is_unique_rejects_missing_name() -> None:
    """A falsy name aborts 400 (the type data must carry a name)."""
    mgr = MagicMock()

    with pytest.raises(HTTPException) as exc_info:
        verify_type_is_unique(mgr, None)

    assert exc_info.value.code == HTTP_BAD_REQUEST


def test_verify_type_is_unique_rejects_taken_special_type() -> None:
    """A special_type already carried by another type aborts 400."""
    mgr = MagicMock()
    mgr.get_one_by.return_value = None
    mgr.check_special_type_exists.return_value = True

    with pytest.raises(HTTPException) as exc_info:
        verify_type_is_unique(mgr, 'name', special_type='SUBNET')

    assert exc_info.value.code == HTTP_BAD_REQUEST


def test_verify_type_is_unique_passes_when_all_clear() -> None:
    """A fresh name, free public_id and unused special_type pass without aborting."""
    mgr = MagicMock()
    mgr.get_type.return_value = None
    mgr.get_one_by.return_value = None
    mgr.check_special_type_exists.return_value = False

    verify_type_is_unique(mgr, 'name', public_id=5, special_type='SUBNET')  # must not raise


# ------------------------------------------------------ verify_type_deletable --------------------------------------- #

def _patch_managers_by_type(managers: dict) -> Any:
    """Patches ManagerProvider.get_manager to return the mock registered for each ManagerType."""
    return patch(f'{PATH}.ManagerProvider.get_manager', side_effect=lambda mtype, _user: managers[mtype])


def _listing_params(
        active: bool = True,
        criteria: Any = None,
        category: int | None = None,
        uncategorized: bool = False) -> SimpleNamespace:
    """The TypeIterationParameters fields the listing helpers read."""
    return SimpleNamespace(
        active=active,
        filter={'name': 'x'} if criteria is None else criteria,
        category=category,
        uncategorized=uncategorized,
    )


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


# ------------------------------------------------------ prepare_builder_parameters ---------------------------------- #

def test_build_type_criteria_adds_active_to_dict_criteria_with_keys() -> None:
    """An active flag is merged into a non-empty dict criteria."""
    assert build_type_criteria({'name': 'x'}, True) == {'name': 'x', TypeSchemaKey.ACTIVE.value: True}


def test_build_type_criteria_keeps_empty_dict_criteria_a_dict() -> None:
    """An empty dict criteria stays a dict instead of becoming a pipeline with an empty $match."""
    assert build_type_criteria({}, True) == {TypeSchemaKey.ACTIVE.value: True}


def test_build_type_criteria_appends_active_match_to_list_criteria() -> None:
    """An active flag is appended as a $match stage to an existing list criteria."""
    result = build_type_criteria([{'$match': {'name': 'x'}}], True)

    assert result == [{'$match': {'name': 'x'}}, {'$match': {TypeSchemaKey.ACTIVE.value: True}}]


def test_build_type_criteria_returns_criteria_unchanged_when_inactive() -> None:
    """A falsy active flag restricts nothing and hands the criteria straight back."""
    client_criteria = {'name': 'x'}

    assert build_type_criteria(client_criteria, False) == {'name': 'x'}


def test_build_type_criteria_does_not_mutate_the_dict_it_was_given() -> None:
    """The client's dict criteria is left exactly as it arrived - it is echoed back in the response."""
    client_criteria = {'name': 'x'}

    build_type_criteria(client_criteria, True)

    assert client_criteria == {'name': 'x'}


def test_build_type_criteria_does_not_mutate_the_list_it_was_given() -> None:
    """The client's list criteria is left exactly as it arrived - it is echoed back in the response."""
    client_criteria = [{'$match': {'name': 'x'}}]

    build_type_criteria(client_criteria, True)

    assert client_criteria == [{'$match': {'name': 'x'}}]


def test_prepare_builder_parameters_passes_the_merged_criteria_to_the_builder() -> None:
    """The merged criteria replaces the criteria the pager handed over."""
    type_params = _listing_params()

    with patch(f'{PATH}.CollectionParameters.get_builder_params',
               return_value={'criteria': {'name': 'x'}, 'limit': 10}), \
         patch(f'{PATH}.BuilderParameters') as builder_params:
        prepare_builder_parameters(type_params, MagicMock())

    assert builder_params.call_args.kwargs['criteria'] == {'name': 'x', TypeSchemaKey.ACTIVE.value: True}
    assert builder_params.call_args.kwargs['limit'] == 10


def test_prepare_builder_parameters_leaves_the_echoed_filter_untouched() -> None:
    """The pager's own filter is never mutated, so the response echoes what the client sent."""
    type_params = _listing_params()

    with patch(f'{PATH}.CollectionParameters.get_builder_params', return_value={'criteria': {'name': 'x'}}), \
         patch(f'{PATH}.BuilderParameters'):
        prepare_builder_parameters(type_params, MagicMock())

    assert type_params.filter == {'name': 'x'}


def test_prepare_builder_parameters_adds_no_category_criteria_without_the_parameters() -> None:
    """An ordinary listing never reaches the CategoriesManager."""
    type_params = _listing_params()

    with patch(f'{PATH}.CollectionParameters.get_builder_params', return_value={'criteria': {}}), \
         patch(f'{PATH}.BuilderParameters') as builder_params, \
         patch(f'{PATH}.ManagerProvider.get_manager') as provider:
        prepare_builder_parameters(type_params, MagicMock())

    provider.assert_not_called()
    builder_params.return_value.add_criteria.assert_not_called()


def test_prepare_builder_parameters_adds_the_category_criteria_when_asked() -> None:
    """A category filter lands on the BuilderParameters, not in the echoed pager filter."""
    type_params = _listing_params(category=4)
    categories = MagicMock()
    categories.get_category_type_ids.return_value = [7, 8]

    with patch(f'{PATH}.CollectionParameters.get_builder_params', return_value={'criteria': {}}), \
         patch(f'{PATH}.BuilderParameters') as builder_params, \
         _patch_managers_by_type({ManagerType.CATEGORIES: categories}):
        prepare_builder_parameters(type_params, MagicMock())

    builder_params.return_value.add_criteria.assert_called_once_with(
        {TypeSchemaKey.PUBLIC_ID.value: {'$in': [7, 8]}}
    )


# ------------------------------------------------------ build_category_criteria ------------------------------------- #

def test_build_category_criteria_returns_none_without_either_parameter() -> None:
    """No category filter was asked for, so nothing is added."""
    with patch(f'{PATH}.ManagerProvider.get_manager') as provider:
        assert build_category_criteria(_listing_params(), MagicMock()) is None

    provider.assert_not_called()


def test_build_category_criteria_restricts_to_the_categorys_types() -> None:
    """?category=<id> filters this collection on the ids the category holds."""
    categories = MagicMock()
    categories.get_category_type_ids.return_value = [7, 8]

    with _patch_managers_by_type({ManagerType.CATEGORIES: categories}):
        criteria = build_category_criteria(_listing_params(category=4), MagicMock())

    categories.get_category_type_ids.assert_called_once_with(4)
    assert criteria == {TypeSchemaKey.PUBLIC_ID.value: {'$in': [7, 8]}}


def test_build_category_criteria_for_an_unassigned_category_matches_nothing() -> None:
    """A category holding no types - or none at all - yields an empty list, not every type."""
    categories = MagicMock()
    categories.get_category_type_ids.return_value = []

    with _patch_managers_by_type({ManagerType.CATEGORIES: categories}):
        criteria = build_category_criteria(_listing_params(category=99), MagicMock())

    assert criteria == {TypeSchemaKey.PUBLIC_ID.value: {'$in': []}}


def test_build_category_criteria_excludes_every_assigned_type_when_uncategorized() -> None:
    """?uncategorized=true is the complement of 'assigned to any category'."""
    categories = MagicMock()
    categories.get_assigned_type_ids.return_value = {9, 2, 5}

    with _patch_managers_by_type({ManagerType.CATEGORIES: categories}):
        criteria = build_category_criteria(_listing_params(uncategorized=True), MagicMock())

    assert criteria == {TypeSchemaKey.PUBLIC_ID.value: {'$nin': [2, 5, 9]}}


def test_build_category_criteria_with_nothing_categorized_excludes_nothing() -> None:
    """Every type is uncategorized when no category holds any."""
    categories = MagicMock()
    categories.get_assigned_type_ids.return_value = set()

    with _patch_managers_by_type({ManagerType.CATEGORIES: categories}):
        criteria = build_category_criteria(_listing_params(uncategorized=True), MagicMock())

    assert criteria == {TypeSchemaKey.PUBLIC_ID.value: {'$nin': []}}


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


# ------------------------------------------------------ type_deletion_followup -------------------------------------- #

def test_type_deletion_followup_runs_generic_cleanup_without_special_type() -> None:
    """The generic cleanup chain runs; special-type un-wiring is skipped without a marker."""
    managers: dict = {}

    with patch(f'{PATH}.ManagerProvider.get_manager', side_effect=lambda mtype, _user: managers.setdefault(
        mtype, MagicMock())), \
         patch(f'{PATH}.cleanup_type_references_from_all_types', return_value=0) as cleanup_refs, \
         patch(f'{PATH}.cleanup_special_type_template_references') as cleanup_special:
        type_deletion_followup(MagicMock(), 7, special_type=None)

    managers[ManagerType.RELATIONS].remove_type_from_relations.assert_called_once_with(7)
    managers[ManagerType.CATEGORIES].remove_type_from_categories.assert_called_once_with(7)
    cleanup_refs.assert_called_once()
    cleanup_special.assert_not_called()


def test_type_deletion_followup_runs_special_type_cleanup_with_marker() -> None:
    """A deleted special type additionally triggers the template-only ref_types un-wiring."""
    with patch(f'{PATH}.ManagerProvider.get_manager', side_effect=lambda mtype, _user: MagicMock()), \
         patch(f'{PATH}.cleanup_type_references_from_all_types', return_value=0), \
         patch(f'{PATH}.cleanup_special_type_template_references') as cleanup_special:
        type_deletion_followup(MagicMock(), 7, special_type='SUBNET')

    cleanup_special.assert_called_once()


def test_type_deletion_followup_reports_the_siblings_it_cleaned(caplog) -> None:
    """
    The sibling cleanup is silent unless it changed something, and then it says how much

    Stripping a deleted type out of other types' `ref_types` is the one step of the chain whose scope
    is not knowable from the request, so the count is the only record that it happened at all.
    """
    with patch(f'{PATH}.ManagerProvider.get_manager', side_effect=lambda mtype, _user: MagicMock()), \
         patch(f'{PATH}.cleanup_type_references_from_all_types', return_value=3), \
         patch(f'{PATH}.cleanup_special_type_template_references'), \
         caplog.at_level(logging.INFO, logger=PATH):
        type_deletion_followup(MagicMock(), 7, special_type=None)

    assert 'Cleaned references to deleted CmdbType 7 from 3' in caplog.text


# ------------------------------------------------------- get_types_user_data ---------------------------------------- #

def _user(display_name: str, image: str) -> MagicMock:
    """A CmdbUser stand-in exposing what the overview row reads."""
    user = MagicMock()
    user.get_display_name.return_value = display_name
    user.image = image

    return user


def test_types_user_data_resolves_both_sides() -> None:
    """The overview row of an edited type names its author AND its last editor"""
    lookup = {1: _user('Author', 'author.png'), 2: _user('Editor', 'editor.png')}

    user_data = get_types_user_data(lookup, author_id=1, editor_id=2)

    assert user_data[TypeUserDataKey.AUTHOR] == 'Author'
    assert user_data[TypeUserDataKey.AUTHOR_IMAGE] == 'author.png'
    assert user_data[TypeUserDataKey.LAST_EDITOR] == 'Editor'
    assert user_data[TypeUserDataKey.LAST_EDITOR_IMAGE] == 'editor.png'


def test_types_user_data_leaves_an_unresolvable_user_null() -> None:
    """
    A never-edited type, and one whose author has been deleted, both read as null rather than raising

    The lookup is built in bulk from the ids the page carries, so a user removed since is simply absent
    from it - the row still has to render.
    """
    user_data = get_types_user_data({1: _user('Author', 'author.png')}, author_id=99, editor_id=None)

    assert user_data == {
        TypeUserDataKey.AUTHOR: None,
        TypeUserDataKey.AUTHOR_IMAGE: None,
        TypeUserDataKey.LAST_EDITOR: None,
        TypeUserDataKey.LAST_EDITOR_IMAGE: None,
    }


# ------------------------------------------------- apply_type_changes_to_locations ---------------------------------- #

def _type_for_location(label: str, icon: str, selectable: bool) -> SimpleNamespace:
    """Builds a CmdbType stand-in exposing the attributes apply_type_changes_to_locations reads."""
    return SimpleNamespace(
        label=label,
        render_meta=SimpleNamespace(icon=icon),
        selectable_as_parent=selectable,
        get_public_id=lambda: 5,
    )


def test_apply_type_changes_to_locations_is_a_noop_without_changes() -> None:
    """When label/icon/selectable are unchanged, no location update is issued."""
    old_type = _type_for_location('L', 'fa-cube', True)
    new_type = _type_for_location('L', 'fa-cube', True)

    with patch(f'{PATH}.ManagerProvider.get_manager') as provider:
        apply_type_changes_to_locations(MagicMock(), old_type, new_type)

    provider.assert_not_called()


def test_apply_type_changes_to_locations_pushes_only_changed_fields() -> None:
    """A changed label propagates as a location update carrying just the changed field."""
    old_type = _type_for_location('Old', 'fa-cube', True)
    new_type = _type_for_location('New', 'fa-cube', True)
    locations = MagicMock()

    with patch(f'{PATH}.ManagerProvider.get_manager', return_value=locations):
        apply_type_changes_to_locations(MagicMock(), old_type, new_type)

    public_id, changed_data = locations.update_locations_by_type.call_args.args
    assert public_id == 5
    assert changed_data == {LocationKey.TYPE_LABEL: 'New'}


# -------------------------------------------------------------------------------------------------------------------- #
#                                          enforce_special_type_license                                                #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('markers', [
    (None,),
    ('',),
    ('NOT-A-SPECIAL-TYPE',),
    (None, None),
], ids=str)
def test_enforce_special_type_license_noop_without_an_ipam_marker(markers: tuple) -> None:
    """A write that touches no IPAM special type never consults the license guard"""
    with patch(f'{PATH}.abort_if_feature_locked') as guard:
        enforce_special_type_license(MagicMock(), *markers)

    guard.assert_not_called()


@pytest.mark.parametrize('marker', [SpecialType.SUPERNET, SpecialType.SUBNET, SpecialType.VLAN], ids=str)
def test_enforce_special_type_license_delegates_for_an_ipam_special_type(marker: SpecialType) -> None:
    """An IPAM special-type write delegates to the IPAM license guard with the request user"""
    request_user = MagicMock()

    with patch(f'{PATH}.abort_if_feature_locked') as guard:
        enforce_special_type_license(request_user, marker)

    guard.assert_called_once_with(LicenseFeature.IPAM, request_user)


def test_enforce_special_type_license_gates_a_rack_behind_ipam() -> None:
    """
    Managing a Rack type requires the IPAM license - an INTERIM policy, not a claim about IPAM

    A Rack is not an IPAM type (SpecialType.get_ipam_types still excludes it) and the Rack View is
    expected to get a LicenseFeature of its own; until then it is gated behind IPAM, so the guard
    matches it via SpecialType.get_license_gated_types.
    """
    request_user = MagicMock()

    with patch(f'{PATH}.abort_if_feature_locked') as guard:
        enforce_special_type_license(request_user, SpecialType.RACK)

    guard.assert_called_once_with(LicenseFeature.IPAM, request_user)


def test_enforce_special_type_license_fires_when_any_marker_is_ipam() -> None:
    """The update route passes stored and requested markers; either one being IPAM gates the write"""
    with patch(f'{PATH}.abort_if_feature_locked') as guard:
        enforce_special_type_license(MagicMock(), None, SpecialType.SUBNET)

    guard.assert_called_once()


# -------------------------------------------------------------------------------------------------------------------- #
#                                           enforce_uses_ports_license                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('requested', [None, False, '', 0], ids=str)
def test_enforce_uses_ports_license_noop_when_the_flag_is_not_requested(requested: Any) -> None:
    """
    A write that does not turn the flag on never consults the license guard

    The absent-key case is the important one: every ordinary type write omits 'uses_ports', and none
    of them may start requiring an IPAM license because of this feature.
    """
    with patch(f'{PATH}.abort_if_feature_locked') as guard:
        enforce_uses_ports_license(MagicMock(), requested)

    guard.assert_not_called()


def test_enforce_uses_ports_license_delegates_when_the_flag_is_turned_on() -> None:
    """Declaring a type as port-bearing delegates to the IPAM license guard with the request user"""
    request_user = MagicMock()

    with patch(f'{PATH}.abort_if_feature_locked') as guard:
        enforce_uses_ports_license(request_user, True)

    guard.assert_called_once_with(LicenseFeature.IPAM, request_user)


def test_enforce_uses_ports_license_allows_turning_the_flag_off() -> None:
    """
    Turning 'uses_ports' off is never gated - cleanup is never blocked

    The guard reads the REQUESTED value only, never the stored one, so a customer whose IPAM license
    lapsed can still switch a port-bearing type back. Same policy as the rack hooks, where leaving a
    rack stays possible unlicensed.
    """
    with patch(f'{PATH}.abort_if_feature_locked') as guard:
        enforce_uses_ports_license(MagicMock(), False)

    guard.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                        enforce_rack_selectable_as_parent                                             #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('special_type', [None, '', SpecialType.SUBNET], ids=str)
def test_enforce_rack_selectable_as_parent_leaves_other_types_untouched(special_type: Any) -> None:
    """Only a Rack has its selectable_as_parent forced; every other type keeps what was sent"""
    data: dict[str, Any] = {TypeSchemaKey.SELECTABLE_AS_PARENT.value: False}

    enforce_rack_selectable_as_parent(special_type, data)

    assert data[TypeSchemaKey.SELECTABLE_AS_PARENT.value] is False


def test_enforce_rack_selectable_as_parent_fills_in_a_missing_value() -> None:
    """A Rack payload that omits the flag gets it set, so the type can parent its members"""
    data: dict[str, Any] = {}

    enforce_rack_selectable_as_parent(SpecialType.RACK, data)

    assert data[TypeSchemaKey.SELECTABLE_AS_PARENT.value] is True


def test_enforce_rack_selectable_as_parent_keeps_an_explicit_true() -> None:
    """An explicit True is already correct and stays"""
    data: dict[str, Any] = {TypeSchemaKey.SELECTABLE_AS_PARENT.value: True}

    enforce_rack_selectable_as_parent(SpecialType.RACK, data)

    assert data[TypeSchemaKey.SELECTABLE_AS_PARENT.value] is True


def test_enforce_rack_selectable_as_parent_aborts_400_on_an_explicit_false() -> None:
    """
    Disabling it on a Rack is refused rather than silently flipped

    A Rack whose type is not selectable as a parent could never have anything placed in it, because
    validate_object_location_change refuses such a parent - so the caller gets a 400 explaining it
    instead of a coercion they cannot see.
    """
    data: dict[str, Any] = {TypeSchemaKey.SELECTABLE_AS_PARENT.value: False}

    with pytest.raises(HTTPException) as err:
        enforce_rack_selectable_as_parent(SpecialType.RACK, data)

    assert err.value.code == 400


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
        Counts only - the equivalent location payload is unbounded for a large Type (backlog #187)

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


# ------------------------------------------- the identifier guards (G1) --------------------------------------------- #
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
