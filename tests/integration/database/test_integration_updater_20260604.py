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
Integration tests for cmdb.database.updater.versions.updater_20260604 against a real MongoDB

The unit tests pin every query and write with mocked managers; these tests run the whole
migration against real collections seeded with a pre-migration baseline: SUPERNET / SUBNET
CmdbTypes without the 'dg-*-type' selector definitions, objects without selector values, a
stored dg-ipam-interface section template without the required flag, a CmdbType using that
template (materialized copy), and a carrier object with un-typed interface MDS rows.

Covered end to end: the selector field definitions land in the type schemas (definition +
section layout), object values are derived from the real CIDRs, the stored template gains
'required: true' and the change propagates into the using type via the real
handle_section_template_changes, interface rows are backfilled with the IP-first / subnet-
fallback precedence, the persisted updater version is bumped, a second run is a no-op
(idempotency), and a migrated subnet passes the save-time enforcement
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager, TypesManager
from cmdb.models.object_model import (
    CmdbObject,
    CmdbObjectKey,
    CmdbObjectFieldKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
    extract_field_value,
)
from cmdb.models.type_model import CmdbType, FieldKey, FieldType, SectionKey, SectionType
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import (
    SupernetField,
    SubnetField,
    InterfaceField,
    IpAddressFamily,
    IpamSection,
)
from cmdb.framework.ipam.enforcement import enforce_object_invariants
from cmdb.database.updater.versions.updater_20260604 import (
    RENDER_META_KEY,
    SECTIONS_KEY,
    Update20260604,
)
# -------------------------------------------------------------------------------------------------------------------- #

SUPERNET_TYPE_ID: int = 9510
SUBNET_TYPE_ID: int = 9511
CARRIER_TYPE_ID: int = 9512

SUPERNET_V4_ID: int = 9520
SUPERNET_V6_ID: int = 9521
SUBNET_V6_ID: int = 9522
SUBNET_BROKEN_ID: int = 9523
CARRIER_ID: int = 9524

TEMPLATE_ID: int = 9530

SUPERNET_RANGE_V4: str = '10.0.0.0/8'
SUPERNET_RANGE_V6: str = '2001:db8::/32'
SUBNET_RANGE_V6: str = '2001:db8:0:1::/64'
UNPARSABLE_RANGE: str = 'not-a-cidr'

ROW_IP_V6: str = '2001:db8:0:1::5'
PRESET_ROW_IP_V4: str = '10.0.0.5'

UPDATER_SETTINGS_ID: str = 'updater'
SETTINGS_COLLECTION: str = 'settings.conf'

TYPE_IDS: list[int] = [SUPERNET_TYPE_ID, SUBNET_TYPE_ID, CARRIER_TYPE_ID]
OBJECT_IDS: list[int] = [SUPERNET_V4_ID, SUPERNET_V6_ID, SUBNET_V6_ID, SUBNET_BROKEN_ID, CARRIER_ID]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   FIXTURES                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
def _field_def(field_type: str, name: str, label: str) -> dict[str, Any]:
    """Builds one CmdbType / template field definition."""
    return {FieldKey.TYPE: field_type, FieldKey.NAME: name, FieldKey.LABEL: label}


def _section(section_type: str, name: str, label: str, field_names: list[str]) -> dict[str, Any]:
    """Builds one render_meta section layout entry."""
    return {
        SectionKey.TYPE: section_type,
        SectionKey.NAME: name,
        SectionKey.LABEL: label,
        SectionKey.FIELDS: field_names,
    }


def _type_doc(
    public_id: int,
    name: str,
    fields: list[dict[str, Any]],
    sections: list[dict[str, Any]],
    special_type: str | None = None,
    global_template_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Builds a baseline (pre-migration) CmdbType document."""
    return {
        CmdbObjectKey.PUBLIC_ID: public_id,
        'name': name,
        'label': name,
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        TypeSchemaKey.FIELDS: fields,
        RENDER_META_KEY: {
            'icon': 'fa-cube',
            SECTIONS_KEY: sections,
            'summary': {SectionKey.FIELDS: []},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': '1.0.0',
        TypeSchemaKey.SPECIAL_TYPE: special_type if special_type is not None else '',
        'global_template_ids': global_template_ids or [],
    }


def _field(name: str, value: Any) -> dict[str, Any]:
    """Builds one stored CmdbObject field / MDS data entry."""
    return {CmdbObjectFieldKey.NAME: name, CmdbObjectFieldKey.VALUE: value}


def _object_doc(
    public_id: int,
    type_id: int,
    fields: list[dict[str, Any]],
    mds: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Builds a baseline CmdbObject document."""
    doc: dict[str, Any] = {
        CmdbObjectKey.PUBLIC_ID: public_id,
        CmdbObjectKey.TYPE_ID: type_id,
        'active': True,
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'version': '1.0.0',
        CmdbObjectKey.FIELDS: fields,
    }

    if mds is not None:
        doc[CmdbObjectKey.MULTI_DATA_SECTIONS] = mds

    return doc


def _baseline_interface_field_defs() -> list[dict[str, Any]]:
    """The pre-migration dg-ipam-interface field definitions: the type SELECT lacks 'required'."""
    return [
        _field_def(FieldType.REFERENCE, InterfaceField.SUBNET, 'Network'),
        _field_def(FieldType.TEXT, InterfaceField.IP, 'IP-Address'),
        {
            FieldKey.TYPE: FieldType.SELECT,
            FieldKey.NAME: InterfaceField.TYPE,
            FieldKey.LABEL: 'Type',
            FieldKey.OPTIONS: [
                {FieldKey.NAME: IpAddressFamily.IPV4, FieldKey.LABEL: 'IPv4'},
                {FieldKey.NAME: IpAddressFamily.IPV6, FieldKey.LABEL: 'IPv6'},
            ],
        },
    ]


@pytest.fixture(scope='module', autouse=True, name='seeded_baseline')
def fixture_seeded_baseline(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the pre-migration baseline (types, objects, template), cleaning up afterwards."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    templates = database_manager.get_collection(CmdbSectionTemplate.COLLECTION, database_name)
    settings = database_manager.get_collection(SETTINGS_COLLECTION, database_name)

    previous_updater_setting: dict[str, Any] | None = settings.find_one({'_id': UPDATER_SETTINGS_ID})

    types.insert_many([
        _type_doc(
            SUPERNET_TYPE_ID, 'it-mig-supernet',
            fields=[
                _field_def(FieldType.TEXT, SupernetField.NAME, 'Name'),
                _field_def(FieldType.TEXT, SupernetField.NETWORK_RANGE, 'Network'),
            ],
            sections=[
                _section(SectionType.SECTION, IpamSection.INFORMATION, 'Information', [SupernetField.NAME]),
                _section(SectionType.SECTION, IpamSection.NETWORK_DETAILS, 'Network Details',
                         [SupernetField.NETWORK_RANGE]),
            ],
            special_type=SpecialType.SUPERNET,
        ),
        _type_doc(
            SUBNET_TYPE_ID, 'it-mig-subnet',
            fields=[
                _field_def(FieldType.TEXT, SubnetField.NAME, 'Name'),
                _field_def(FieldType.REFERENCE, SubnetField.PARENT_SUPERNET, 'Supernet'),
                _field_def(FieldType.TEXT, SubnetField.NETWORK_RANGE, 'Network'),
            ],
            sections=[
                _section(SectionType.SECTION, IpamSection.INFORMATION, 'Information', [SubnetField.NAME]),
                _section(SectionType.SECTION, IpamSection.NETWORK_DETAILS, 'Network Details',
                         [SubnetField.PARENT_SUPERNET, SubnetField.NETWORK_RANGE]),
            ],
            special_type=SpecialType.SUBNET,
        ),
        _type_doc(
            CARRIER_TYPE_ID, 'it-mig-carrier',
            fields=_baseline_interface_field_defs(),
            sections=[
                _section(SectionType.MDS_SECTION, IpamSection.INTERFACE, 'Interfaces',
                         [InterfaceField.SUBNET, InterfaceField.IP, InterfaceField.TYPE]),
            ],
            global_template_ids=[IpamSection.INTERFACE],
        ),
    ])

    templates.insert_one({
        CmdbObjectKey.PUBLIC_ID: TEMPLATE_ID,
        SectionKey.NAME: IpamSection.INTERFACE,
        SectionKey.LABEL: 'Interfaces',
        SectionKey.TYPE: SectionType.MDS_SECTION,
        'is_global': True,
        'predefined': True,
        TypeSchemaKey.FIELDS: _baseline_interface_field_defs(),
    })

    objects.insert_many([
        _object_doc(SUPERNET_V4_ID, SUPERNET_TYPE_ID, [
            _field(SupernetField.NAME, 'mig-sn4'),
            _field(SupernetField.NETWORK_RANGE, SUPERNET_RANGE_V4),
        ]),
        _object_doc(SUPERNET_V6_ID, SUPERNET_TYPE_ID, [
            _field(SupernetField.NAME, 'mig-sn6'),
            _field(SupernetField.NETWORK_RANGE, SUPERNET_RANGE_V6),
        ]),
        _object_doc(SUBNET_V6_ID, SUBNET_TYPE_ID, [
            _field(SubnetField.NAME, 'mig-sub6'),
            _field(SubnetField.PARENT_SUPERNET, SUPERNET_V6_ID),
            _field(SubnetField.NETWORK_RANGE, SUBNET_RANGE_V6),
        ]),
        _object_doc(SUBNET_BROKEN_ID, SUBNET_TYPE_ID, [
            _field(SubnetField.NAME, 'mig-broken'),
            _field(SubnetField.NETWORK_RANGE, UNPARSABLE_RANGE),
        ]),
        _object_doc(CARRIER_ID, CARRIER_TYPE_ID, [], mds=[{
            CmdbObjectMdsKey.SECTION_ID: IpamSection.INTERFACE,
            CmdbObjectMdsKey.VALUES: [
                # row 0: IP decides the family
                {CmdbObjectMdsRowKey.DATA: [
                    _field(InterfaceField.SUBNET, SUBNET_V6_ID),
                    _field(InterfaceField.IP, ROW_IP_V6),
                ]},
                # row 1: no IP - the referenced subnet's family decides
                {CmdbObjectMdsRowKey.DATA: [
                    _field(InterfaceField.SUBNET, SUBNET_V6_ID),
                ]},
                # row 2: empty placeholder - must stay untouched
                {CmdbObjectMdsRowKey.DATA: []},
                # row 3: already typed - the stored value is never overwritten
                {CmdbObjectMdsRowKey.DATA: [
                    _field(InterfaceField.IP, PRESET_ROW_IP_V4),
                    _field(InterfaceField.TYPE, IpAddressFamily.IPV6),
                ]},
            ],
        }]),
    ])

    yield

    types.delete_many({CmdbObjectKey.PUBLIC_ID: {'$in': TYPE_IDS}})
    objects.delete_many({CmdbObjectKey.PUBLIC_ID: {'$in': OBJECT_IDS}})
    templates.delete_many({CmdbObjectKey.PUBLIC_ID: TEMPLATE_ID})

    if previous_updater_setting is not None:
        settings.replace_one({'_id': UPDATER_SETTINGS_ID}, previous_updater_setting, upsert=True)
    else:
        settings.delete_many({'_id': UPDATER_SETTINGS_ID})


@pytest.fixture(scope='module', autouse=True, name='run_updater')
def fixture_run_updater(seeded_baseline, database_manager: MongoDatabaseManager, database_name: str):  # pylint: disable=unused-argument
    """Runs the migration once against the seeded baseline; depends on it purely for ordering."""
    Update20260604(database_manager, database_name).start_update()
    yield


@pytest.fixture(name='types_collection')
def fixture_types_collection(database_manager: MongoDatabaseManager, database_name: str):
    """Provides the raw CmdbType collection."""
    return database_manager.get_collection(CmdbType.COLLECTION, database_name)


@pytest.fixture(name='objects_collection')
def fixture_objects_collection(database_manager: MongoDatabaseManager, database_name: str):
    """Provides the raw CmdbObject collection."""
    return database_manager.get_collection(CmdbObject.COLLECTION, database_name)


def _field_value(doc: dict[str, Any], field_name: str) -> Any:
    """Reads one stored object field value."""
    return extract_field_value(doc, field_name)


def _type_field_def(type_doc: dict[str, Any], field_name: str) -> dict[str, Any] | None:
    """Returns a CmdbType document's field definition by name."""
    return next(
        (f for f in type_doc.get(TypeSchemaKey.FIELDS, []) if f.get(FieldKey.NAME) == field_name),
        None,
    )


# -------------------------------------------------------------------------------------------------------------------- #
#                                              TYPE DEFINITIONS                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('type_id, selector, anchor', [
    (SUPERNET_TYPE_ID, SupernetField.TYPE, SupernetField.NETWORK_RANGE),
    (SUBNET_TYPE_ID, SubnetField.TYPE, SubnetField.NETWORK_RANGE),
], ids=['supernet', 'subnet'])
def test_selector_definition_added_to_the_special_type(
    types_collection, type_id: int, selector: str, anchor: str,
) -> None:
    """The required SELECT lands in the type's fields and before the range in the section layout"""
    type_doc = types_collection.find_one({CmdbObjectKey.PUBLIC_ID: type_id})

    field_def = _type_field_def(type_doc, selector)
    assert field_def is not None
    assert field_def[FieldKey.REQUIRED] is True
    assert field_def[FieldKey.TYPE] == FieldType.SELECT

    network_details = next(
        s for s in type_doc[RENDER_META_KEY][SECTIONS_KEY]
        if s[SectionKey.NAME] == IpamSection.NETWORK_DETAILS
    )
    layout: list[str] = network_details[SectionKey.FIELDS]
    assert layout.index(selector) == layout.index(anchor) - 1


# -------------------------------------------------------------------------------------------------------------------- #
#                                              OBJECT VALUE BACKFILL                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('object_id, selector, expected_family', [
    (SUPERNET_V4_ID, SupernetField.TYPE, IpAddressFamily.IPV4),
    (SUPERNET_V6_ID, SupernetField.TYPE, IpAddressFamily.IPV6),
    (SUBNET_V6_ID, SubnetField.TYPE, IpAddressFamily.IPV6),
    (SUBNET_BROKEN_ID, SubnetField.TYPE, IpAddressFamily.IPV4),
], ids=['supernet-v4', 'supernet-v6', 'subnet-v6', 'subnet-unparsable-default'])
def test_object_selector_values_derive_from_the_real_cidrs(
    objects_collection, object_id: int, selector: str, expected_family: str,
) -> None:
    """Every object's selector value matches its range family (ipv4 for the unparsable range)"""
    doc = objects_collection.find_one({CmdbObjectKey.PUBLIC_ID: object_id})

    assert _field_value(doc, selector) == expected_family


# -------------------------------------------------------------------------------------------------------------------- #
#                                         TEMPLATE + PROPAGATION                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def test_stored_template_gains_the_required_flag(
    database_manager: MongoDatabaseManager, database_name: str,
) -> None:
    """The stored dg-ipam-interface template's type SELECT is now required"""
    templates = database_manager.get_collection(CmdbSectionTemplate.COLLECTION, database_name)
    template_doc = templates.find_one({CmdbObjectKey.PUBLIC_ID: TEMPLATE_ID})

    type_def = _type_field_def(template_doc, InterfaceField.TYPE)
    assert type_def is not None
    assert type_def[FieldKey.REQUIRED] is True


def test_template_change_propagates_into_the_using_type(types_collection) -> None:
    """The carrier type's materialized template copy carries the required flag exactly once"""
    carrier_doc = types_collection.find_one({CmdbObjectKey.PUBLIC_ID: CARRIER_TYPE_ID})

    matching_defs = [
        f for f in carrier_doc[TypeSchemaKey.FIELDS] if f.get(FieldKey.NAME) == InterfaceField.TYPE
    ]
    assert len(matching_defs) == 1
    assert matching_defs[0][FieldKey.REQUIRED] is True

    interface_section = next(
        s for s in carrier_doc[RENDER_META_KEY][SECTIONS_KEY]
        if s[SectionKey.NAME] == IpamSection.INTERFACE
    )
    assert interface_section[SectionKey.FIELDS].count(InterfaceField.TYPE) == 1


# -------------------------------------------------------------------------------------------------------------------- #
#                                            INTERFACE ROW BACKFILL                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_interface_rows_backfilled_with_ip_first_subnet_fallback(objects_collection) -> None:
    """Row families: IP-derived, subnet-derived, untouched placeholder, preserved preset value"""
    carrier = objects_collection.find_one({CmdbObjectKey.PUBLIC_ID: CARRIER_ID})
    rows = carrier[CmdbObjectKey.MULTI_DATA_SECTIONS][0][CmdbObjectMdsKey.VALUES]

    def row_type(index: int) -> Any:
        return next(
            (e[CmdbObjectFieldKey.VALUE] for e in rows[index][CmdbObjectMdsRowKey.DATA]
             if e[CmdbObjectFieldKey.NAME] == InterfaceField.TYPE),
            None,
        )

    assert row_type(0) == IpAddressFamily.IPV6      # from the IPv6 IP
    assert row_type(1) == IpAddressFamily.IPV6      # from the referenced subnet's family
    assert rows[2][CmdbObjectMdsRowKey.DATA] == []  # empty placeholder untouched
    assert row_type(3) == IpAddressFamily.IPV6      # preset value never overwritten


# -------------------------------------------------------------------------------------------------------------------- #
#                                          VERSION + IDEMPOTENCY + ENFORCEMENT                                         #
# -------------------------------------------------------------------------------------------------------------------- #
def test_persisted_updater_version_is_bumped(
    database_manager: MongoDatabaseManager, database_name: str,
) -> None:
    """The settings document records the migration version"""
    settings = database_manager.get_collection(SETTINGS_COLLECTION, database_name)
    setting = settings.find_one({'_id': UPDATER_SETTINGS_ID})

    assert setting['version'] == 20260604


def test_migrated_subnet_passes_save_time_enforcement(
    database_manager: MongoDatabaseManager, objects_collection,
) -> None:
    """End to end: a migrated subnet object satisfies the new required-selector enforcement"""
    objects_manager = ObjectsManager(database_manager)
    types_manager = TypesManager(database_manager)
    subnet_doc = objects_collection.find_one({CmdbObjectKey.PUBLIC_ID: SUBNET_V6_ID}, {'_id': 0})

    errors = enforce_object_invariants(objects_manager, types_manager, subnet_doc, subnet_doc)

    assert not errors


def test_second_run_is_idempotent(
    database_manager: MongoDatabaseManager, database_name: str, types_collection, objects_collection,
) -> None:
    """Re-running the migration changes nothing: no duplicate defs, layout entries or values"""
    subnet_type_before = types_collection.find_one({CmdbObjectKey.PUBLIC_ID: SUBNET_TYPE_ID}, {'_id': 0})
    carrier_before = objects_collection.find_one({CmdbObjectKey.PUBLIC_ID: CARRIER_ID}, {'_id': 0})

    Update20260604(database_manager, database_name).start_update()

    subnet_type_after = types_collection.find_one({CmdbObjectKey.PUBLIC_ID: SUBNET_TYPE_ID}, {'_id': 0})
    carrier_after = objects_collection.find_one({CmdbObjectKey.PUBLIC_ID: CARRIER_ID}, {'_id': 0})

    assert subnet_type_after == subnet_type_before
    assert carrier_after == carrier_before

    selector_defs = [
        f for f in subnet_type_after[TypeSchemaKey.FIELDS] if f.get(FieldKey.NAME) == SubnetField.TYPE
    ]
    assert len(selector_defs) == 1
