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
Database update 20260604: backfill the required IPAM address-family selectors

The IPAM validators now require the address-family selectors on save: 'dg-supernet-type' on
SUPERNETs, 'dg-subnet-type' on SUBNETs and 'dg-interface-type' on every data-carrying
dg-ipam-interface MDS row. The live baseline predates those fields, so this update brings an
existing installation to the new state:

1. Adds the required SELECT field definition to the existing SUPERNET / SUBNET CmdbTypes
   (schema 'fields' entry plus the Network-Details section layout) when it is missing, syncs
   the key attributes ('type', 'options', 'required') of an already-present definition to the
   blueprint, and syncs the 'dg-network-range' regex to the blueprint's dual-family
   CIDR_REGEX (the baseline regex only admitted IPv4)
2. Backfills the selector on every SUPERNET / SUBNET CmdbObject as a complete
   {name, value, type} field entry, deriving the value from the object's 'dg-network-range'
   CIDR family ('ipv4' when the range is missing or unparsable - the baseline is IPv4-only)
3. Ensures the stored dg-ipam-interface section template carries the required
   'dg-interface-type' SELECT, syncs the 'dg-interface-ip-address' regex to the blueprint's
   dual-family IP_ADDRESS_REGEX (the baseline field had no regex), and propagates the
   template change to every CmdbType using it via handle_section_template_changes
4. Backfills 'dg-interface-type' on every data-carrying interface MDS row as a complete
   {name, value, type} entry: the parsed IP's family first, the referenced subnet's family
   second, 'ipv4' as last resort; empty placeholder rows are left untouched

Every step only touches documents that lack the value (or, for already-present entries and
definitions, only fills the missing attributes), so re-running on partially migrated data is
safe - including data written by a pre-fix run of this updater whose object entries lack the
'type' key
"""
from logging import Logger, getLogger
from copy import deepcopy
from typing import Any

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate
from cmdb.manager.section_templates_manager import SectionTemplatesManager
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.object_model import (
    CmdbObjectKey,
    CmdbObjectFieldKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
    extract_field_value,
)
from cmdb.models.type_model import FieldKey, FieldType, SectionKey
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import (
    SupernetField,
    SubnetField,
    InterfaceField,
    IpAddressFamily,
    IpamSection,
)
from cmdb.models.special_type_model.schemas.supernet_schema import get_supernet_schema
from cmdb.models.special_type_model.schemas.subnet_schema import get_subnet_schema
from cmdb.framework.section_templates.section_template_creator import SectionTemplateCreator
from cmdb.framework.ipam.cidr import parse_cidr, parse_ip, network_family, address_family

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# Document keys of a stored CmdbType that have no shared enum (TypeSchemaKey names the
# blueprint keys; the persisted document nests the section layout under 'render_meta')
RENDER_META_KEY: str = 'render_meta'
SECTIONS_KEY: str = 'sections'

# Blueprint attributes synced onto an already-present field definition; the user-visible
# 'label' and any local extras are deliberately left untouched
SYNCED_FIELD_DEF_KEYS: tuple[str, ...] = (FieldKey.TYPE, FieldKey.OPTIONS, FieldKey.REQUIRED)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  PURE HELPERS                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def derive_family_from_range(raw_range: Any) -> str:
    """
    Returns the address-family token of a stored network-range value

    Args:
        raw_range (Any): The raw 'dg-network-range' field value

    Returns:
        str: The parsed CIDR's IpAddressFamily; IpAddressFamily.IPV4 when the value is
            missing or unparsable (the live baseline is IPv4-only)
    """
    network = parse_cidr(raw_range) if isinstance(raw_range, str) else None

    return network_family(network) if network is not None else IpAddressFamily.IPV4


def coerce_subnet_ref(value: Any) -> int | None:
    """
    Coerces a stored subnet-reference value into an int public_id when possible, else None

    Args:
        value (Any): The raw dg-interface-subnet value

    Returns:
        int | None: The integer public_id, or None when 'value' carries no usable reference
    """
    if value is None or value == '' or value == 0:
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def derive_row_family(
    subnet_ref: Any,
    ip_address: Any,
    family_by_subnet_id: dict[int, str],
) -> str | None:
    """
    Returns the address-family token for one dg-ipam-interface row, or None for an empty row

    Precedence: the parsed IP's family wins when the row carries a parsable IP; otherwise the
    referenced subnet's family from ``family_by_subnet_id``; otherwise IPv4 as last resort.
    A row without any data (no usable subnet ref, no non-empty IP) returns None so empty
    placeholder rows are left untouched - the save-time enforcement also ignores them

    Args:
        subnet_ref (Any): The raw dg-interface-subnet value of the row
        ip_address (Any): The raw dg-interface-ip-address value of the row
        family_by_subnet_id (dict[int, str]): {subnet public_id: IpAddressFamily} map of the
            existing SUBNET objects

    Returns:
        str | None: The derived IpAddressFamily token, or None when the row carries no data
    """
    coerced_ref: int | None = coerce_subnet_ref(subnet_ref)
    has_ip: bool = isinstance(ip_address, str) and bool(ip_address)

    if not has_ip and coerced_ref is None:
        return None

    if has_ip:
        parsed = parse_ip(ip_address)

        if parsed is not None:
            return address_family(parsed)

    if coerced_ref is not None and coerced_ref in family_by_subnet_id:
        return family_by_subnet_id[coerced_ref]

    return IpAddressFamily.IPV4


def ensure_field_value(fields: list[dict[str, Any]], field_name: str, value: str, field_type: str) -> bool:
    """
    Ensures a fields/data list carries a complete {name, value, type} entry for the field name

    A stored object field entry must always carry all three keys: 'name', 'value' and 'type'
    (the FieldType of the field's definition). An existing entry keeps a non-empty value and a
    non-empty type; whichever of the two is missing or empty is set; a missing entry is
    appended as a full triple. The list is mutated in place

    Args:
        fields (list[dict[str, Any]]): A CmdbObject 'fields' list or an MDS row 'data' list
        field_name (str): The field name to ensure
        value (str): The value to set when missing
        field_type (str): The FieldType of the field's definition (e.g. FieldType.SELECT)

    Returns:
        bool: True when the list was changed
    """
    for entry in fields:
        if entry.get(CmdbObjectFieldKey.NAME) != field_name:
            continue

        changed: bool = False
        current_value: Any = entry.get(CmdbObjectFieldKey.VALUE)
        current_type: Any = entry.get(CmdbObjectFieldKey.TYPE)

        if not (isinstance(current_value, str) and current_value):
            entry[CmdbObjectFieldKey.VALUE] = value
            changed = True

        if not (isinstance(current_type, str) and current_type):
            entry[CmdbObjectFieldKey.TYPE] = field_type
            changed = True

        return changed

    fields.append({
        CmdbObjectFieldKey.NAME: field_name,
        CmdbObjectFieldKey.VALUE: value,
        CmdbObjectFieldKey.TYPE: field_type,
    })
    return True


def ensure_field_definition(fields: list[dict[str, Any]], field_def: dict[str, Any]) -> bool:
    """
    Ensures a field-definition list contains the given definition with its key attributes

    A missing definition is appended verbatim; a present definition gets every
    SYNCED_FIELD_DEF_KEYS attribute ('type', 'options', 'required') synced from the blueprint
    when it is missing or differs, while the rest of the existing definition (e.g. a locally
    customized 'label') is left untouched. The list is mutated in place

    Args:
        fields (list[dict[str, Any]]): A CmdbType or section-template 'fields' definition list
        field_def (dict[str, Any]): The blueprint definition (must carry 'name')

    Returns:
        bool: True when the list was changed
    """
    existing: dict[str, Any] | None = next(
        (f for f in fields if f.get(FieldKey.NAME) == field_def.get(FieldKey.NAME)),
        None,
    )

    if existing is None:
        fields.append(field_def)
        return True

    changed: bool = False

    for key in SYNCED_FIELD_DEF_KEYS:
        if key in field_def and existing.get(key) != field_def[key]:
            existing[key] = field_def[key]
            changed = True

    return changed


def ensure_field_regex(fields: list[dict[str, Any]], field_name: str, regex: str) -> bool:
    """
    Ensures a field-definition list carries the given regex on the named field

    The live baseline shipped the IPAM address fields with an IPv4-only regex (network range)
    or no regex at all (interface IP), so a stored definition whose regex differs from the
    blueprint value is synced - covering both the replace and the add case. A definition list
    without the field is left untouched (there is nothing to attach the regex to). The list
    is mutated in place

    Args:
        fields (list[dict[str, Any]]): A CmdbType or section-template 'fields' definition list
        field_name (str): The field name whose regex is synced
        regex (str): The blueprint regex to set

    Returns:
        bool: True when the list was changed
    """
    existing: dict[str, Any] | None = next(
        (f for f in fields if f.get(FieldKey.NAME) == field_name),
        None,
    )

    if existing is None or existing.get(FieldKey.REGEX) == regex:
        return False

    existing[FieldKey.REGEX] = regex
    return True


def ensure_section_layout(
    type_doc: dict[str, Any],
    field_name: str,
    section_name: str,
    before_field: str,
) -> bool:
    """
    Ensures a CmdbType's section layout lists the given field name

    When the field is already listed in any section nothing changes. Otherwise the field is
    inserted into the section named ``section_name`` (falling back to the section that lists
    ``before_field``), directly before ``before_field`` when present, else appended. A type
    without any sections is left untouched (degenerate definition; logged). The document is
    mutated in place

    Args:
        type_doc (dict[str, Any]): The stored CmdbType document
        field_name (str): The field name to place into the layout
        section_name (str): The preferred section to receive the field
        before_field (str): The anchor field the new field should precede

    Returns:
        bool: True when the layout was changed
    """
    sections: list[dict[str, Any]] = (type_doc.get(RENDER_META_KEY) or {}).get(SECTIONS_KEY) or []

    for section in sections:
        if field_name in (section.get(SectionKey.FIELDS) or []):
            return False

    target: dict[str, Any] | None = next(
        (s for s in sections if s.get(SectionKey.NAME) == section_name),
        None,
    )

    if target is None:
        target = next(
            (s for s in sections if before_field in (s.get(SectionKey.FIELDS) or [])),
            None,
        )

    if target is None:
        LOGGER.warning(
            "[updater 20260604] Type %s has no section to place field '%s' into; layout unchanged",
            type_doc.get(CmdbObjectKey.PUBLIC_ID), field_name,
        )
        return False

    section_fields: list[str] = target.setdefault(SectionKey.FIELDS, [])

    if before_field in section_fields:
        section_fields.insert(section_fields.index(before_field), field_name)
    else:
        section_fields.append(field_name)

    return True


def backfill_interface_rows(
    mds_sections: list[dict[str, Any]],
    family_by_subnet_id: dict[int, str],
) -> bool:
    """
    Backfills 'dg-interface-type' on every data-carrying dg-ipam-interface row

    Rows without any data are left untouched. Rows that already carry a non-empty type value
    keep it, but an entry still lacking the 'type' key (written by a pre-fix run) is repaired
    to the full {name, value, type} shape; for the rest the family is derived via
    ``derive_row_family``. The sections are mutated in place

    Args:
        mds_sections (list[dict[str, Any]]): A CmdbObject's 'multi_data_sections' list
        family_by_subnet_id (dict[int, str]): {subnet public_id: IpAddressFamily} map of the
            existing SUBNET objects

    Returns:
        bool: True when at least one row was changed
    """
    changed: bool = False

    for section in mds_sections or []:
        if section.get(CmdbObjectMdsKey.SECTION_ID) != IpamSection.INTERFACE:
            continue

        for row in section.get(CmdbObjectMdsKey.VALUES, []) or []:
            data: Any = row.get(CmdbObjectMdsRowKey.DATA)

            if not isinstance(data, list):
                continue

            entries: dict[Any, Any] = {
                entry.get(CmdbObjectFieldKey.NAME): entry.get(CmdbObjectFieldKey.VALUE)
                for entry in data
            }
            current_type: Any = entries.get(InterfaceField.TYPE)

            if isinstance(current_type, str) and current_type:
                # Value already present - still repair an entry that lacks the 'type' key
                changed = ensure_field_value(
                    data, InterfaceField.TYPE, current_type, FieldType.SELECT,
                ) or changed
                continue

            family: str | None = derive_row_family(
                entries.get(InterfaceField.SUBNET),
                entries.get(InterfaceField.IP),
                family_by_subnet_id,
            )

            if family is None:
                continue

            changed = ensure_field_value(data, InterfaceField.TYPE, family, FieldType.SELECT) or changed

    return changed


def get_interface_field_def(field_name: str) -> dict[str, Any]:
    """
    Returns one field definition from the predefined dg-ipam-interface template blueprint

    Pulled from SectionTemplateCreator so the updater and fresh installations share one
    source of truth for the definitions (the required type SELECT, the dual-family IP regex)

    Args:
        field_name (str): The field name to extract (InterfaceField.TYPE / InterfaceField.IP)

    Returns:
        dict[str, Any]: The blueprint field definition
    """
    templates: list[dict[str, Any]] = SectionTemplateCreator().get_predefined_templates()
    interface: dict[str, Any] = next(
        t for t in templates if t.get(SectionKey.NAME) == IpamSection.INTERFACE
    )

    return next(
        f for f in interface[TypeSchemaKey.FIELDS] if f.get(FieldKey.NAME) == field_name
    )


def get_selector_field_def(blueprint: dict[str, Any], field_name: str) -> dict[str, Any]:
    """
    Returns one field definition from a SpecialType schema blueprint by field name

    Args:
        blueprint (dict[str, Any]): Output of get_supernet_schema / get_subnet_schema
        field_name (str): The field name to extract (the 'dg-*-type' selector or the
            'dg-network-range' field)

    Returns:
        dict[str, Any]: The blueprint field definition
    """
    return next(f for f in blueprint[TypeSchemaKey.FIELDS] if f.get(FieldKey.NAME) == field_name)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                Update20260604 - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class Update20260604(BaseDatabaseUpdate):
    """
    Backfills the now-required IPAM address-family selectors on types, the stored
    dg-ipam-interface section template, and all existing objects / interface rows, and syncs
    the baseline IPv4-only field regexes to the dual-family blueprint values
    """
    def creation_date(self) -> int:
        return 20260604


    def description(self) -> str:
        return ("Adds the required IPAM address-family selectors ('dg-supernet-type', 'dg-subnet-type', "
                "'dg-interface-type') to the existing SUPERNET/SUBNET types and the dg-ipam-interface "
                "section template, syncs the network-range and interface-IP regexes to the dual-family "
                "(IPv4/IPv6) blueprints, and backfills the values on all existing objects and interface rows")


    def start_update(self) -> None:
        """
        Runs the four migration steps (type definitions, object values, template, MDS rows)
        and bumps the persisted updater version
        """
        try:
            self.backfill_special_type(
                SpecialType.SUPERNET,
                get_supernet_schema(),
                SupernetField.TYPE,
                SupernetField.NETWORK_RANGE,
            )
            family_by_subnet_id: dict[int, str] = self.backfill_special_type(
                SpecialType.SUBNET,
                get_subnet_schema(),
                SubnetField.TYPE,
                SubnetField.NETWORK_RANGE,
            )

            self.update_interface_template()
            self.backfill_interface_carriers(family_by_subnet_id)

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(str(err)) from err


    def backfill_special_type(
        self,
        special_type: SpecialType,
        blueprint: dict[str, Any],
        type_field: str,
        range_field: str,
    ) -> dict[int, str]:
        """
        Adds the selector field to the SpecialType's CmdbType, syncs the network-range regex
        to the blueprint's dual-family value, and backfills every object

        Returns the {public_id: family} map of the type's objects so the SUBNET pass can feed
        the interface-row backfill without a second load. A missing SpecialType (the
        installation never created it) is a silent no-op

        Args:
            special_type (SpecialType): SUPERNET or SUBNET
            blueprint (dict[str, Any]): The SpecialType's schema blueprint
            type_field (str): The selector field name (SupernetField.TYPE / SubnetField.TYPE)
            range_field (str): The network-range field name the family is derived from

        Returns:
            dict[int, str]: {object public_id: IpAddressFamily} for every object of the type
        """
        type_doc: dict[str, Any] | None = self.types_manager.get_one_by(
            {TypeSchemaKey.SPECIAL_TYPE: special_type},
        )

        if not type_doc:
            return {}

        field_def: dict[str, Any] = get_selector_field_def(blueprint, type_field)
        type_fields: list[dict[str, Any]] = type_doc.setdefault(TypeSchemaKey.FIELDS, [])

        type_changed: bool = ensure_field_definition(type_fields, field_def)
        type_changed = ensure_field_regex(
            type_fields, range_field,
            get_selector_field_def(blueprint, range_field)[FieldKey.REGEX],
        ) or type_changed
        type_changed = ensure_section_layout(
            type_doc, type_field, IpamSection.NETWORK_DETAILS, range_field,
        ) or type_changed

        if type_changed:
            self.types_manager.update_type(type_doc[CmdbObjectKey.PUBLIC_ID], type_doc)

        family_by_id: dict[int, str] = {}

        objects: list[dict[str, Any]] = self.objects_manager.find_objects(
            {CmdbObjectKey.TYPE_ID: type_doc[CmdbObjectKey.PUBLIC_ID]},
            as_dict=True,
        )

        for obj in objects:
            family: str = derive_family_from_range(extract_field_value(obj, range_field))
            family_by_id[obj[CmdbObjectKey.PUBLIC_ID]] = family

            obj_fields: list[dict[str, Any]] = obj.setdefault(CmdbObjectKey.FIELDS, [])

            if ensure_field_value(obj_fields, type_field, family, field_def[FieldKey.TYPE]):
                self.objects_manager.update_many_raw(
                    filter_query={CmdbObjectKey.PUBLIC_ID: obj[CmdbObjectKey.PUBLIC_ID]},
                    update={'$set': {CmdbObjectKey.FIELDS: obj_fields}},
                )

        return family_by_id


    def update_interface_template(self) -> None:
        """
        Ensures the stored dg-ipam-interface template carries the required type selector and
        the dual-family IP regex, and propagates the changes to every CmdbType using the
        template

        Mirrors the section-template update route: persist the changed template via
        update_section_template, then run handle_section_template_changes with the original
        template so the field diff lands in every materialized section copy. A missing stored
        template (fresh installation creates it with the flag already set) is a silent no-op
        """
        section_templates_manager = SectionTemplatesManager(self.dbm, self.db_name)

        template_doc: dict[str, Any] | None = section_templates_manager.get_one_by(
            {SectionKey.NAME: IpamSection.INTERFACE},
        )

        if not template_doc:
            return

        current_template: CmdbSectionTemplate = CmdbSectionTemplate.from_data(deepcopy(template_doc))

        new_params: dict[str, Any] = deepcopy(template_doc)
        new_fields: list[dict[str, Any]] = new_params.setdefault(TypeSchemaKey.FIELDS, [])

        def_changed: bool = ensure_field_definition(
            new_fields, get_interface_field_def(InterfaceField.TYPE),
        )
        regex_changed: bool = ensure_field_regex(
            new_fields, InterfaceField.IP,
            get_interface_field_def(InterfaceField.IP)[FieldKey.REGEX],
        )

        if not (def_changed or regex_changed):
            return

        section_templates_manager.update_section_template(
            new_params[CmdbObjectKey.PUBLIC_ID], new_params,
        )
        section_templates_manager.handle_section_template_changes(new_params, current_template)


    def backfill_interface_carriers(self, family_by_subnet_id: dict[int, str]) -> None:
        """
        Backfills 'dg-interface-type' on every object carrying dg-ipam-interface MDS rows

        Args:
            family_by_subnet_id (dict[int, str]): {subnet public_id: IpAddressFamily} map of
                the existing SUBNET objects
        """
        criteria: dict[str, Any] = {
            CmdbObjectKey.MULTI_DATA_SECTIONS: {
                '$elemMatch': {CmdbObjectMdsKey.SECTION_ID: IpamSection.INTERFACE},
            },
        }

        carriers: list[dict[str, Any]] = self.objects_manager.find_objects(criteria, as_dict=True)

        for carrier in carriers:
            mds_sections: list[dict[str, Any]] = carrier.get(CmdbObjectKey.MULTI_DATA_SECTIONS) or []

            if backfill_interface_rows(mds_sections, family_by_subnet_id):
                self.objects_manager.update_many_raw(
                    filter_query={CmdbObjectKey.PUBLIC_ID: carrier[CmdbObjectKey.PUBLIC_ID]},
                    update={'$set': {CmdbObjectKey.MULTI_DATA_SECTIONS: mds_sections}},
                )
