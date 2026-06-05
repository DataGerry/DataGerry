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
Unit tests for cmdb.database.updater.versions.updater_20260604

Covers the pure helpers (family derivation, field-value / field-definition / field-regex /
section-layout ensurers, interface-row backfill, blueprint extraction) and the orchestration methods with
mocked managers, following the established version-updater test pattern (instances built via
__new__ with the needed managers attached). The metadata contract (creation_date /
description) is covered by the shared parametrized test in test_version_updaters
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.models.object_model import (
    CmdbObjectKey,
    CmdbObjectFieldKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
)
from cmdb.models.type_model import FieldKey, SectionKey
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import (
    SupernetField,
    SubnetField,
    InterfaceField,
    IpAddressFamily,
    IpamSection,
)
from cmdb.models.special_type_model.schemas.subnet_schema import get_subnet_schema
from cmdb.models.special_type_model.schemas.supernet_schema import get_supernet_schema
from cmdb.models.special_type_model.schemas.cidr_regex import CIDR_REGEX, IP_ADDRESS_REGEX
from cmdb.errors.updater import UpdaterException
from cmdb.database.updater.versions.updater_20260604 import (
    RENDER_META_KEY,
    SECTIONS_KEY,
    Update20260604,
    backfill_interface_rows,
    coerce_subnet_ref,
    derive_family_from_range,
    derive_row_family,
    ensure_field_definition,
    ensure_field_regex,
    ensure_field_value,
    ensure_section_layout,
    get_interface_field_def,
    get_selector_field_def,
)
# -------------------------------------------------------------------------------------------------------------------- #

PATH: str = 'cmdb.database.updater.versions.updater_20260604'

SUPERNET_TYPE_ID: int = 10
SUBNET_TYPE_ID: int = 11
SUBNET_OBJECT_ID: int = 201
CARRIER_OBJECT_ID: int = 301
TEMPLATE_PUBLIC_ID: int = 7

RANGE_V4: str = '10.0.0.0/24'
RANGE_V6: str = '2001:db8::/64'
UNPARSABLE_RANGE: str = 'not-a-cidr'

IP_V4: str = '10.0.0.5'
IP_V6: str = '2001:db8::5'

# The pre-migration baseline regex of 'dg-network-range' (IPv4-only, replaced by CIDR_REGEX)
LEGACY_IPV4_CIDR_REGEX: str = (
    r'^(?:(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]\d?|0)'
    r'(?:\.(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]\d?|0)){3})'
    r'/(?:3[0-2]|[12]?\d)$'
)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   FIXTURES                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
def _make_field_entry(name: str, value: Any) -> dict[str, Any]:
    """Builds one stored field/data entry."""
    return {CmdbObjectFieldKey.NAME: name, CmdbObjectFieldKey.VALUE: value}


def _make_interface_row(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Builds one MDS interface row from prepared data entries."""
    return {CmdbObjectMdsRowKey.DATA: entries}


def _make_interface_sections(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Builds a multi_data_sections list with one dg-ipam-interface section."""
    return [{
        CmdbObjectMdsKey.SECTION_ID: IpamSection.INTERFACE,
        CmdbObjectMdsKey.VALUES: rows,
    }]


def _make_type_doc(
    public_id: int,
    fields: list[dict[str, Any]],
    sections: list[dict[str, Any]],
) -> dict[str, Any]:
    """Builds a stored CmdbType document with fields and a render_meta section layout."""
    return {
        CmdbObjectKey.PUBLIC_ID: public_id,
        TypeSchemaKey.FIELDS: fields,
        RENDER_META_KEY: {SECTIONS_KEY: sections},
    }


def _make_section(name: str, field_names: list[str]) -> dict[str, Any]:
    """Builds one render_meta section layout entry."""
    return {SectionKey.NAME: name, SectionKey.FIELDS: field_names}


# -------------------------------------------------------------------------------------------------------------------- #
#                                              derive_family_from_range                                                #
# -------------------------------------------------------------------------------------------------------------------- #
def test_derive_family_from_range_maps_parsable_cidrs_to_their_family() -> None:
    """IPv4 and IPv6 ranges resolve to their actual family"""
    assert derive_family_from_range(RANGE_V4) == IpAddressFamily.IPV4
    assert derive_family_from_range(RANGE_V6) == IpAddressFamily.IPV6


@pytest.mark.parametrize('bad_range', [None, 123, UNPARSABLE_RANGE, '10.0.0.5/24'])
def test_derive_family_from_range_defaults_to_ipv4(bad_range: Any) -> None:
    """Missing, non-string or unparsable ranges fall back to the IPv4 baseline default"""
    assert derive_family_from_range(bad_range) == IpAddressFamily.IPV4


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 coerce_subnet_ref                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_coerce_subnet_ref_passes_ints_and_digit_strings_through() -> None:
    """Numeric refs coerce to the int public_id"""
    assert coerce_subnet_ref(SUBNET_OBJECT_ID) == SUBNET_OBJECT_ID
    assert coerce_subnet_ref(str(SUBNET_OBJECT_ID)) == SUBNET_OBJECT_ID


@pytest.mark.parametrize('empty_value', [None, '', 0, UNPARSABLE_RANGE])
def test_coerce_subnet_ref_treats_unusable_values_as_none(empty_value: Any) -> None:
    """None, empty markers and garbage coerce to None"""
    assert coerce_subnet_ref(empty_value) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 derive_row_family                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_derive_row_family_returns_none_for_empty_rows() -> None:
    """A row without subnet ref and IP stays untouched (None)"""
    assert derive_row_family(None, None, {}) is None
    assert derive_row_family('', '', {}) is None


def test_derive_row_family_prefers_the_parsed_ip() -> None:
    """A parsable IP decides the family even when the subnet map disagrees"""
    family = derive_row_family(SUBNET_OBJECT_ID, IP_V6, {SUBNET_OBJECT_ID: IpAddressFamily.IPV4})

    assert family == IpAddressFamily.IPV6


def test_derive_row_family_falls_back_to_the_subnet_family() -> None:
    """Without a parsable IP the referenced subnet's family decides"""
    assert derive_row_family(SUBNET_OBJECT_ID, None, {SUBNET_OBJECT_ID: IpAddressFamily.IPV6}) \
        == IpAddressFamily.IPV6
    assert derive_row_family(SUBNET_OBJECT_ID, 'not-an-ip', {SUBNET_OBJECT_ID: IpAddressFamily.IPV6}) \
        == IpAddressFamily.IPV6


def test_derive_row_family_defaults_to_ipv4_as_last_resort() -> None:
    """Unparsable IP without subnet, and a dangling subnet ref, both default to ipv4"""
    assert derive_row_family(None, 'not-an-ip', {}) == IpAddressFamily.IPV4
    assert derive_row_family(SUBNET_OBJECT_ID, None, {}) == IpAddressFamily.IPV4


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 ensure_field_value                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_ensure_field_value_appends_a_missing_entry() -> None:
    """A fields list without the entry gains it and reports a change"""
    fields: list[dict[str, Any]] = []

    assert ensure_field_value(fields, SubnetField.TYPE, IpAddressFamily.IPV4) is True
    assert fields == [_make_field_entry(SubnetField.TYPE, IpAddressFamily.IPV4)]


def test_ensure_field_value_sets_an_empty_entry() -> None:
    """An entry with None / empty value is set in place"""
    fields = [_make_field_entry(SubnetField.TYPE, None)]

    assert ensure_field_value(fields, SubnetField.TYPE, IpAddressFamily.IPV6) is True
    assert fields[0][CmdbObjectFieldKey.VALUE] == IpAddressFamily.IPV6


def test_ensure_field_value_keeps_an_existing_value() -> None:
    """A non-empty value is never overwritten"""
    fields = [_make_field_entry(SubnetField.TYPE, IpAddressFamily.IPV6)]

    assert ensure_field_value(fields, SubnetField.TYPE, IpAddressFamily.IPV4) is False
    assert fields[0][CmdbObjectFieldKey.VALUE] == IpAddressFamily.IPV6


# -------------------------------------------------------------------------------------------------------------------- #
#                                              ensure_field_definition                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_ensure_field_definition_appends_a_missing_definition() -> None:
    """A definition list without the field gains the blueprint def verbatim"""
    field_def = get_selector_field_def(get_subnet_schema(), SubnetField.TYPE)
    fields: list[dict[str, Any]] = []

    assert ensure_field_definition(fields, field_def) is True
    assert fields == [field_def]


def test_ensure_field_definition_marks_an_existing_definition_required() -> None:
    """A present definition only gets required=True; other keys stay untouched"""
    existing = {FieldKey.NAME: SubnetField.TYPE, FieldKey.LABEL: 'Custom Label'}
    fields = [existing]

    assert ensure_field_definition(fields, get_selector_field_def(get_subnet_schema(), SubnetField.TYPE)) is True
    assert existing[FieldKey.REQUIRED] is True
    assert existing[FieldKey.LABEL] == 'Custom Label'


def test_ensure_field_definition_is_a_noop_when_already_required() -> None:
    """An already-required definition reports no change"""
    fields = [{FieldKey.NAME: SubnetField.TYPE, FieldKey.REQUIRED: True}]

    assert ensure_field_definition(fields, get_selector_field_def(get_subnet_schema(), SubnetField.TYPE)) is False


# -------------------------------------------------------------------------------------------------------------------- #
#                                                ensure_field_regex                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_ensure_field_regex_replaces_a_legacy_regex() -> None:
    """A field carrying the IPv4-only baseline regex is synced to the blueprint value"""
    field = {FieldKey.NAME: SubnetField.NETWORK_RANGE, FieldKey.REGEX: LEGACY_IPV4_CIDR_REGEX}
    fields = [field]

    assert ensure_field_regex(fields, SubnetField.NETWORK_RANGE, CIDR_REGEX) is True
    assert field[FieldKey.REGEX] == CIDR_REGEX


def test_ensure_field_regex_adds_a_missing_regex() -> None:
    """A field without any regex (the baseline interface IP field) gains the blueprint value"""
    field = {FieldKey.NAME: InterfaceField.IP, FieldKey.LABEL: 'IP-Address'}
    fields = [field]

    assert ensure_field_regex(fields, InterfaceField.IP, IP_ADDRESS_REGEX) is True
    assert field[FieldKey.REGEX] == IP_ADDRESS_REGEX


def test_ensure_field_regex_is_a_noop_when_already_current() -> None:
    """A field already carrying the blueprint regex reports no change"""
    fields = [{FieldKey.NAME: SubnetField.NETWORK_RANGE, FieldKey.REGEX: CIDR_REGEX}]

    assert ensure_field_regex(fields, SubnetField.NETWORK_RANGE, CIDR_REGEX) is False


def test_ensure_field_regex_skips_an_absent_field() -> None:
    """A definition list without the field is left untouched"""
    fields: list[dict[str, Any]] = [{FieldKey.NAME: SubnetField.NAME}]

    assert ensure_field_regex(fields, SubnetField.NETWORK_RANGE, CIDR_REGEX) is False
    assert fields == [{FieldKey.NAME: SubnetField.NAME}]


# -------------------------------------------------------------------------------------------------------------------- #
#                                               ensure_section_layout                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_ensure_section_layout_inserts_before_the_anchor_in_the_named_section() -> None:
    """The field lands directly before the network-range anchor in the preferred section"""
    type_doc = _make_type_doc(SUBNET_TYPE_ID, [], [
        _make_section(IpamSection.NETWORK_DETAILS, [SubnetField.PARENT_SUPERNET, SubnetField.NETWORK_RANGE]),
    ])

    changed = ensure_section_layout(
        type_doc, SubnetField.TYPE, IpamSection.NETWORK_DETAILS, SubnetField.NETWORK_RANGE,
    )

    assert changed is True
    assert type_doc[RENDER_META_KEY][SECTIONS_KEY][0][SectionKey.FIELDS] == [
        SubnetField.PARENT_SUPERNET, SubnetField.TYPE, SubnetField.NETWORK_RANGE,
    ]


def test_ensure_section_layout_falls_back_to_the_section_holding_the_anchor() -> None:
    """Without the preferred section, the section listing the anchor receives the field"""
    type_doc = _make_type_doc(SUBNET_TYPE_ID, [], [
        _make_section(IpamSection.INFORMATION, [SubnetField.NAME, SubnetField.NETWORK_RANGE]),
    ])

    changed = ensure_section_layout(
        type_doc, SubnetField.TYPE, IpamSection.NETWORK_DETAILS, SubnetField.NETWORK_RANGE,
    )

    assert changed is True
    assert type_doc[RENDER_META_KEY][SECTIONS_KEY][0][SectionKey.FIELDS] == [
        SubnetField.NAME, SubnetField.TYPE, SubnetField.NETWORK_RANGE,
    ]


def test_ensure_section_layout_is_a_noop_when_the_field_is_listed_anywhere() -> None:
    """A field already placed in any section leaves the layout untouched"""
    type_doc = _make_type_doc(SUBNET_TYPE_ID, [], [
        _make_section(IpamSection.INFORMATION, [SubnetField.TYPE]),
    ])

    assert ensure_section_layout(
        type_doc, SubnetField.TYPE, IpamSection.NETWORK_DETAILS, SubnetField.NETWORK_RANGE,
    ) is False


def test_ensure_section_layout_skips_types_without_sections() -> None:
    """A degenerate type without sections is left untouched instead of erroring"""
    type_doc = _make_type_doc(SUBNET_TYPE_ID, [], [])

    assert ensure_section_layout(
        type_doc, SubnetField.TYPE, IpamSection.NETWORK_DETAILS, SubnetField.NETWORK_RANGE,
    ) is False


# -------------------------------------------------------------------------------------------------------------------- #
#                                              backfill_interface_rows                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_backfill_interface_rows_fills_untyped_data_rows() -> None:
    """Rows carrying data without a type get the derived family written into their data"""
    row = _make_interface_row([
        _make_field_entry(InterfaceField.SUBNET, SUBNET_OBJECT_ID),
        _make_field_entry(InterfaceField.IP, IP_V6),
    ])
    sections = _make_interface_sections([row])

    changed = backfill_interface_rows(sections, {SUBNET_OBJECT_ID: IpAddressFamily.IPV6})

    assert changed is True
    assert _make_field_entry(InterfaceField.TYPE, IpAddressFamily.IPV6) in row[CmdbObjectMdsRowKey.DATA]


def test_backfill_interface_rows_skips_typed_and_empty_rows() -> None:
    """A row with a non-empty type and an empty placeholder row stay untouched"""
    typed_row = _make_interface_row([
        _make_field_entry(InterfaceField.IP, IP_V4),
        _make_field_entry(InterfaceField.TYPE, IpAddressFamily.IPV4),
    ])
    empty_row = _make_interface_row([])
    sections = _make_interface_sections([typed_row, empty_row])

    assert backfill_interface_rows(sections, {}) is False
    assert empty_row[CmdbObjectMdsRowKey.DATA] == []


def test_backfill_interface_rows_sets_an_empty_type_entry_in_place() -> None:
    """A row whose type entry exists but is empty gets the value set on that entry"""
    type_entry = _make_field_entry(InterfaceField.TYPE, '')
    row = _make_interface_row([_make_field_entry(InterfaceField.IP, IP_V4), type_entry])
    sections = _make_interface_sections([row])

    assert backfill_interface_rows(sections, {}) is True
    assert type_entry[CmdbObjectFieldKey.VALUE] == IpAddressFamily.IPV4


def test_backfill_interface_rows_ignores_other_sections() -> None:
    """Rows of non-interface MDS sections are never touched"""
    row = _make_interface_row([_make_field_entry(InterfaceField.IP, IP_V4)])
    sections = [{
        CmdbObjectMdsKey.SECTION_ID: IpamSection.INFORMATION,
        CmdbObjectMdsKey.VALUES: [row],
    }]

    assert backfill_interface_rows(sections, {}) is False


# -------------------------------------------------------------------------------------------------------------------- #
#                                              blueprint extraction                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_get_interface_field_def_returns_the_required_type_select() -> None:
    """The extracted template definition is the required dg-interface-type SELECT"""
    field_def = get_interface_field_def(InterfaceField.TYPE)

    assert field_def[FieldKey.NAME] == InterfaceField.TYPE
    assert field_def[FieldKey.REQUIRED] is True


def test_get_interface_field_def_returns_the_dual_family_ip_regex() -> None:
    """The extracted IP definition carries the dual-family blueprint regex"""
    field_def = get_interface_field_def(InterfaceField.IP)

    assert field_def[FieldKey.NAME] == InterfaceField.IP
    assert field_def[FieldKey.REGEX] == IP_ADDRESS_REGEX


def test_get_selector_field_def_extracts_from_both_blueprints() -> None:
    """The subnet and supernet selector definitions resolve by name from their schemas"""
    subnet_def = get_selector_field_def(get_subnet_schema(), SubnetField.TYPE)
    supernet_def = get_selector_field_def(get_supernet_schema(), SupernetField.TYPE)

    assert subnet_def[FieldKey.NAME] == SubnetField.TYPE
    assert supernet_def[FieldKey.NAME] == SupernetField.TYPE
    assert subnet_def[FieldKey.REQUIRED] is True
    assert supernet_def[FieldKey.REQUIRED] is True


# -------------------------------------------------------------------------------------------------------------------- #
#                                              backfill_special_type                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def _new_updater() -> Update20260604:
    """Builds the updater without its real __init__ (tests attach the mocks they need)."""
    return Update20260604.__new__(Update20260604)


def test_backfill_special_type_is_a_noop_without_the_special_type() -> None:
    """An installation that never created the SpecialType yields {} and no writes"""
    updater = _new_updater()
    updater.types_manager = types_manager = MagicMock()
    types_manager.get_one_by.return_value = None
    updater.objects_manager = objects_manager = MagicMock()

    result = updater.backfill_special_type(
        SpecialType.SUBNET, get_subnet_schema(), SubnetField.TYPE, SubnetField.NETWORK_RANGE,
    )

    assert not result
    types_manager.update_type.assert_not_called()
    objects_manager.find_objects.assert_not_called()


def test_backfill_special_type_adds_definition_and_backfills_objects() -> None:
    """The selector def lands in the type, objects get derived values, the family map returns"""
    updater = _new_updater()
    type_doc = _make_type_doc(SUBNET_TYPE_ID, [], [
        _make_section(IpamSection.NETWORK_DETAILS, [SubnetField.NETWORK_RANGE]),
    ])
    subnet_obj = {
        CmdbObjectKey.PUBLIC_ID: SUBNET_OBJECT_ID,
        CmdbObjectKey.FIELDS: [_make_field_entry(SubnetField.NETWORK_RANGE, RANGE_V6)],
    }
    updater.types_manager = types_manager = MagicMock()
    types_manager.get_one_by.return_value = type_doc
    updater.objects_manager = objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [subnet_obj]

    result = updater.backfill_special_type(
        SpecialType.SUBNET, get_subnet_schema(), SubnetField.TYPE, SubnetField.NETWORK_RANGE,
    )

    types_manager.update_type.assert_called_once_with(SUBNET_TYPE_ID, type_doc)
    assert any(f[FieldKey.NAME] == SubnetField.TYPE for f in type_doc[TypeSchemaKey.FIELDS])
    assert type_doc[RENDER_META_KEY][SECTIONS_KEY][0][SectionKey.FIELDS] == [
        SubnetField.TYPE, SubnetField.NETWORK_RANGE,
    ]

    objects_manager.update_many_raw.assert_called_once_with(
        filter_query={CmdbObjectKey.PUBLIC_ID: SUBNET_OBJECT_ID},
        update={'$set': {CmdbObjectKey.FIELDS: subnet_obj[CmdbObjectKey.FIELDS]}},
    )
    assert _make_field_entry(SubnetField.TYPE, IpAddressFamily.IPV6) in subnet_obj[CmdbObjectKey.FIELDS]
    assert result == {SUBNET_OBJECT_ID: IpAddressFamily.IPV6}


def test_backfill_special_type_syncs_the_legacy_range_regex() -> None:
    """A type migrated except for the IPv4-only range regex gets exactly the regex synced"""
    updater = _new_updater()
    selector_def = get_selector_field_def(get_subnet_schema(), SubnetField.TYPE)
    range_def = {FieldKey.NAME: SubnetField.NETWORK_RANGE, FieldKey.REGEX: LEGACY_IPV4_CIDR_REGEX}
    type_doc = _make_type_doc(SUBNET_TYPE_ID, [selector_def, range_def], [
        _make_section(IpamSection.NETWORK_DETAILS, [SubnetField.TYPE, SubnetField.NETWORK_RANGE]),
    ])
    updater.types_manager = types_manager = MagicMock()
    types_manager.get_one_by.return_value = type_doc
    updater.objects_manager = objects_manager = MagicMock()
    objects_manager.find_objects.return_value = []

    updater.backfill_special_type(
        SpecialType.SUBNET, get_subnet_schema(), SubnetField.TYPE, SubnetField.NETWORK_RANGE,
    )

    types_manager.update_type.assert_called_once_with(SUBNET_TYPE_ID, type_doc)
    assert range_def[FieldKey.REGEX] == CIDR_REGEX


def test_backfill_special_type_writes_nothing_on_migrated_data() -> None:
    """A type with the required def, current regex and objects with values produce no update calls"""
    updater = _new_updater()
    field_def = get_selector_field_def(get_subnet_schema(), SubnetField.TYPE)
    range_def = {FieldKey.NAME: SubnetField.NETWORK_RANGE, FieldKey.REGEX: CIDR_REGEX}
    type_doc = _make_type_doc(SUBNET_TYPE_ID, [field_def, range_def], [
        _make_section(IpamSection.NETWORK_DETAILS, [SubnetField.TYPE, SubnetField.NETWORK_RANGE]),
    ])
    subnet_obj = {
        CmdbObjectKey.PUBLIC_ID: SUBNET_OBJECT_ID,
        CmdbObjectKey.FIELDS: [
            _make_field_entry(SubnetField.NETWORK_RANGE, RANGE_V4),
            _make_field_entry(SubnetField.TYPE, IpAddressFamily.IPV4),
        ],
    }
    updater.types_manager = types_manager = MagicMock()
    types_manager.get_one_by.return_value = type_doc
    updater.objects_manager = objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [subnet_obj]

    result = updater.backfill_special_type(
        SpecialType.SUBNET, get_subnet_schema(), SubnetField.TYPE, SubnetField.NETWORK_RANGE,
    )

    types_manager.update_type.assert_not_called()
    objects_manager.update_many_raw.assert_not_called()
    assert result == {SUBNET_OBJECT_ID: IpAddressFamily.IPV4}


# -------------------------------------------------------------------------------------------------------------------- #
#                                            update_interface_template                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_update_interface_template_is_a_noop_without_a_stored_template() -> None:
    """No stored dg-ipam-interface template (fresh install) → nothing is written"""
    updater = _new_updater()
    updater.dbm = MagicMock()
    updater.db_name = 'cmdb-test'
    manager = MagicMock()
    manager.get_one_by.return_value = None

    with patch(f'{PATH}.SectionTemplatesManager', return_value=manager):
        updater.update_interface_template()

    manager.update_section_template.assert_not_called()
    manager.handle_section_template_changes.assert_not_called()


def test_update_interface_template_persists_and_propagates_the_required_flag() -> None:
    """A stored template lacking required=True is updated and propagated with the original"""
    updater = _new_updater()
    updater.dbm = MagicMock()
    updater.db_name = 'cmdb-test'
    template_doc: dict[str, Any] = {
        CmdbObjectKey.PUBLIC_ID: TEMPLATE_PUBLIC_ID,
        SectionKey.NAME: IpamSection.INTERFACE,
        SectionKey.LABEL: 'Interfaces',
        TypeSchemaKey.FIELDS: [{FieldKey.NAME: InterfaceField.TYPE, FieldKey.LABEL: 'Type'}],
    }
    manager = MagicMock()
    manager.get_one_by.return_value = template_doc
    original_template = MagicMock()

    with patch(f'{PATH}.SectionTemplatesManager', return_value=manager), \
         patch(f'{PATH}.CmdbSectionTemplate') as mock_model:
        mock_model.from_data.return_value = original_template
        updater.update_interface_template()

    update_args = manager.update_section_template.call_args.args
    assert update_args[0] == TEMPLATE_PUBLIC_ID
    new_params = update_args[1]
    assert new_params[TypeSchemaKey.FIELDS][0][FieldKey.REQUIRED] is True
    # the original (pre-change) template is what the diff runs against
    manager.handle_section_template_changes.assert_called_once_with(new_params, original_template)
    # the stored doc itself was deep-copied, not mutated
    assert FieldKey.REQUIRED not in template_doc[TypeSchemaKey.FIELDS][0]


def test_update_interface_template_syncs_the_missing_ip_regex() -> None:
    """A template migrated except for the regex-less IP field is updated and propagated"""
    updater = _new_updater()
    updater.dbm = MagicMock()
    updater.db_name = 'cmdb-test'
    template_doc: dict[str, Any] = {
        CmdbObjectKey.PUBLIC_ID: TEMPLATE_PUBLIC_ID,
        SectionKey.NAME: IpamSection.INTERFACE,
        SectionKey.LABEL: 'Interfaces',
        TypeSchemaKey.FIELDS: [
            {FieldKey.NAME: InterfaceField.TYPE, FieldKey.REQUIRED: True},
            {FieldKey.NAME: InterfaceField.IP, FieldKey.LABEL: 'IP-Address'},
        ],
    }
    manager = MagicMock()
    manager.get_one_by.return_value = template_doc

    with patch(f'{PATH}.SectionTemplatesManager', return_value=manager):
        updater.update_interface_template()

    new_params = manager.update_section_template.call_args.args[1]
    ip_def = next(
        f for f in new_params[TypeSchemaKey.FIELDS] if f[FieldKey.NAME] == InterfaceField.IP
    )
    assert ip_def[FieldKey.REGEX] == IP_ADDRESS_REGEX
    manager.handle_section_template_changes.assert_called_once()


def test_update_interface_template_skips_when_already_migrated() -> None:
    """A template with the required type field and current IP regex produces no writes"""
    updater = _new_updater()
    updater.dbm = MagicMock()
    updater.db_name = 'cmdb-test'
    template_doc: dict[str, Any] = {
        CmdbObjectKey.PUBLIC_ID: TEMPLATE_PUBLIC_ID,
        SectionKey.NAME: IpamSection.INTERFACE,
        SectionKey.LABEL: 'Interfaces',
        TypeSchemaKey.FIELDS: [
            {FieldKey.NAME: InterfaceField.TYPE, FieldKey.REQUIRED: True},
            {FieldKey.NAME: InterfaceField.IP, FieldKey.REGEX: IP_ADDRESS_REGEX},
        ],
    }
    manager = MagicMock()
    manager.get_one_by.return_value = template_doc

    with patch(f'{PATH}.SectionTemplatesManager', return_value=manager):
        updater.update_interface_template()

    manager.update_section_template.assert_not_called()
    manager.handle_section_template_changes.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                           backfill_interface_carriers                                                #
# -------------------------------------------------------------------------------------------------------------------- #
def test_backfill_interface_carriers_updates_only_changed_objects() -> None:
    """A carrier with an untyped row is written back; an already-typed carrier is not"""
    updater = _new_updater()
    untyped = {
        CmdbObjectKey.PUBLIC_ID: CARRIER_OBJECT_ID,
        CmdbObjectKey.MULTI_DATA_SECTIONS: _make_interface_sections([
            _make_interface_row([_make_field_entry(InterfaceField.IP, IP_V4)]),
        ]),
    }
    typed = {
        CmdbObjectKey.PUBLIC_ID: CARRIER_OBJECT_ID + 1,
        CmdbObjectKey.MULTI_DATA_SECTIONS: _make_interface_sections([
            _make_interface_row([
                _make_field_entry(InterfaceField.IP, IP_V4),
                _make_field_entry(InterfaceField.TYPE, IpAddressFamily.IPV4),
            ]),
        ]),
    }
    updater.objects_manager = objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [untyped, typed]

    updater.backfill_interface_carriers({})

    objects_manager.update_many_raw.assert_called_once_with(
        filter_query={CmdbObjectKey.PUBLIC_ID: CARRIER_OBJECT_ID},
        update={'$set': {CmdbObjectKey.MULTI_DATA_SECTIONS: untyped[CmdbObjectKey.MULTI_DATA_SECTIONS]}},
    )


def test_backfill_interface_carriers_pins_the_carrier_criteria() -> None:
    """Carriers are selected via one elemMatch on the interface section id"""
    updater = _new_updater()
    updater.objects_manager = objects_manager = MagicMock()
    objects_manager.find_objects.return_value = []

    updater.backfill_interface_carriers({})

    objects_manager.find_objects.assert_called_once_with(
        {
            CmdbObjectKey.MULTI_DATA_SECTIONS: {
                '$elemMatch': {CmdbObjectMdsKey.SECTION_ID: IpamSection.INTERFACE},
            },
        },
        as_dict=True,
    )


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   start_update                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def test_start_update_runs_all_steps_and_bumps_the_version() -> None:
    """The four steps run in order and the persisted version is bumped afterwards"""
    updater = _new_updater()
    updater.settings_manager = settings_manager = MagicMock()
    family_map: dict[int, str] = {SUBNET_OBJECT_ID: IpAddressFamily.IPV4}

    with patch.object(Update20260604, 'backfill_special_type', return_value=family_map) as mock_types, \
         patch.object(Update20260604, 'update_interface_template') as mock_template, \
         patch.object(Update20260604, 'backfill_interface_carriers') as mock_rows:
        updater.start_update()

    assert mock_types.call_count == 2
    assert mock_types.call_args_list[0].args[0] == SpecialType.SUPERNET
    assert mock_types.call_args_list[1].args[0] == SpecialType.SUBNET
    mock_template.assert_called_once_with()
    mock_rows.assert_called_once_with(family_map)
    settings_manager.write.assert_called_once_with(
        _id='updater', data={'_id': 'updater', 'version': 20260604},
    )


def test_start_update_wraps_failures_in_updater_exception() -> None:
    """Any error from a step surfaces as UpdaterException and the version is not bumped"""
    updater = _new_updater()
    updater.settings_manager = settings_manager = MagicMock()

    with patch.object(Update20260604, 'backfill_special_type', side_effect=RuntimeError('boom')):
        with pytest.raises(UpdaterException):
            updater.start_update()

    settings_manager.write.assert_not_called()


def test_ensure_section_layout_appends_when_the_anchor_is_absent_from_the_target() -> None:
    """A named target section without the anchor field gets the field appended at the end"""
    type_doc = _make_type_doc(SUBNET_TYPE_ID, [], [
        _make_section(IpamSection.NETWORK_DETAILS, [SubnetField.PARENT_SUPERNET]),
    ])

    changed = ensure_section_layout(
        type_doc, SubnetField.TYPE, IpamSection.NETWORK_DETAILS, SubnetField.NETWORK_RANGE,
    )

    assert changed is True
    assert type_doc[RENDER_META_KEY][SECTIONS_KEY][0][SectionKey.FIELDS] == [
        SubnetField.PARENT_SUPERNET, SubnetField.TYPE,
    ]


def test_backfill_interface_rows_skips_rows_with_malformed_data() -> None:
    """A row whose 'data' is not a list is skipped instead of erroring"""
    malformed_row: dict[str, Any] = {CmdbObjectMdsRowKey.DATA: 'not-a-list'}
    sections = _make_interface_sections([malformed_row])

    assert backfill_interface_rows(sections, {}) is False
    assert malformed_row[CmdbObjectMdsRowKey.DATA] == 'not-a-list'
