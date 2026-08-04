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
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.models.type_model import FieldKey, FieldType, SectionType, TypeSchemaKey
from cmdb.models.object_model import CmdbObjectKey, CmdbObjectFieldKey
from cmdb.manager.manager_provider_model import ManagerType
from cmdb.database.predefined_data.predefined_data_constants import LocationKey
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types import types_helper
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_constants import TypeOverviewKey
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_helper import (
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
    prepare_builder_parameters,
    get_objects_using_location_field,
    type_deletion_followup,
    apply_type_changes_to_locations,
    enforce_special_type_license,
    enforce_rack_selectable_as_parent,
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

    with _patch_managers_by_type({ManagerType.OBJECTS: objects, ManagerType.REPORTS: reports}):
        with pytest.raises(HTTPException) as exc_info:
            verify_type_deletable(MagicMock(), 1, {TypeSchemaKey.PUBLIC_ID.value: 1})

    assert exc_info.value.code == HTTP_BAD_REQUEST


def test_verify_type_deletable_aborts_400_when_reports_use_it() -> None:
    """A type still referenced by reports cannot be deleted (400)."""
    objects = MagicMock()
    objects.count_documents.return_value = 0
    reports = MagicMock()
    reports.count_documents.return_value = 2

    with _patch_managers_by_type({ManagerType.OBJECTS: objects, ManagerType.REPORTS: reports}):
        with pytest.raises(HTTPException) as exc_info:
            verify_type_deletable(MagicMock(), 1, {TypeSchemaKey.PUBLIC_ID.value: 1})

    assert exc_info.value.code == HTTP_BAD_REQUEST


def test_verify_type_deletable_passes_when_unused() -> None:
    """No objects and no reports means the type may be deleted (no abort)."""
    objects = MagicMock()
    objects.count_documents.return_value = 0
    reports = MagicMock()
    reports.count_documents.return_value = 0

    with _patch_managers_by_type({ManagerType.OBJECTS: objects, ManagerType.REPORTS: reports}):
        verify_type_deletable(MagicMock(), 1, {TypeSchemaKey.PUBLIC_ID.value: 1})  # must not raise


# ------------------------------------------------------ prepare_builder_parameters ---------------------------------- #

def test_prepare_builder_parameters_adds_active_to_dict_filter_with_keys() -> None:
    """An active flag is merged into a non-empty dict filter."""
    type_params = SimpleNamespace(active=True, filter={'name': 'x'})

    with patch(f'{PATH}.CollectionParameters.get_builder_params', return_value={}), \
         patch(f'{PATH}.BuilderParameters'):
        prepare_builder_parameters(type_params)

    assert type_params.filter[TypeSchemaKey.ACTIVE.value] is True


def test_prepare_builder_parameters_wraps_empty_dict_filter_into_match_list() -> None:
    """An empty dict filter is turned into a two-stage $match list carrying the active flag."""
    type_params = SimpleNamespace(active=True, filter={})

    with patch(f'{PATH}.CollectionParameters.get_builder_params', return_value={}), \
         patch(f'{PATH}.BuilderParameters'):
        prepare_builder_parameters(type_params)

    assert isinstance(type_params.filter, list)
    assert type_params.filter[0]['$match'][TypeSchemaKey.ACTIVE.value] is True


def test_prepare_builder_parameters_appends_active_match_to_list_filter() -> None:
    """An active flag is appended as a $match stage to an existing list filter."""
    type_params = SimpleNamespace(active=True, filter=[{'$match': {'name': 'x'}}])

    with patch(f'{PATH}.CollectionParameters.get_builder_params', return_value={}), \
         patch(f'{PATH}.BuilderParameters'):
        prepare_builder_parameters(type_params)

    assert type_params.filter[-1] == {'$match': {TypeSchemaKey.ACTIVE.value: True}}


def test_prepare_builder_parameters_leaves_filter_untouched_when_inactive() -> None:
    """A falsy active flag leaves the filter unmodified."""
    type_params = SimpleNamespace(active=False, filter={'name': 'x'})

    with patch(f'{PATH}.CollectionParameters.get_builder_params', return_value={}), \
         patch(f'{PATH}.BuilderParameters'):
        prepare_builder_parameters(type_params)

    assert type_params.filter == {'name': 'x'}


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


def test_enforce_special_type_license_does_not_gate_a_rack() -> None:
    """
    A Rack is a SpecialType that IPAM does not own, so managing one needs no IPAM license

    The guard used to fire on the mere presence of a 'special_type' marker, which would have made
    creating a Rack type require an IPAM license.
    """
    with patch(f'{PATH}.abort_if_feature_locked') as guard:
        enforce_special_type_license(MagicMock(), SpecialType.RACK)

    guard.assert_not_called()


def test_enforce_special_type_license_fires_when_any_marker_is_ipam() -> None:
    """The update route passes stored and requested markers; either one being IPAM gates the write"""
    with patch(f'{PATH}.abort_if_feature_locked') as guard:
        enforce_special_type_license(MagicMock(), None, SpecialType.SUBNET)

    guard.assert_called_once()


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
