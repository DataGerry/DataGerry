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
Key, icon and category constants for the DataGerry assistant profile builder

The assistant constructs CmdbType and CmdbCategory dicts from hard-coded profile definitions.
This module names every dict key and literal the builder reads or writes programmatically so a
typo surfaces as an ImportError / AttributeError instead of a silently ignored key.

Keys that also exist in a CmdbType schema reuse the shared FieldKey / SectionKey / TypeSchemaKey
enums from cmdb.models.type_model; the enums below cover only the keys that are private to the
assistant's intermediate representation (the section/field dicts the profiles hand to the
ProfileTypeConstructor) plus the category metadata. All string enums extend BaseStrEnum so members
compare equal to their string value for dict lookup, equality and JSON serialization
"""
from typing import Any

from cmdb.utils import BaseStrEnum
from cmdb.models.special_type_model.special_type_enum import SpecialType
# -------------------------------------------------------------------------------------------------------------------- #


class TypeSlotKey(BaseStrEnum):
    """
    Keys of the 'created_type_ids' dict threaded through the whole profile-creation run

    Each member is the slot under which one created CmdbType's public_id is stored so later
    profiles can reference earlier types (e.g. a Client referencing the Operating System). A
    slot is None until its type is created; conditional sections are only emitted once every
    referenced slot is populated
    """
    COMPANY_ID = 'company_id'
    USER_ID = 'user_id'
    CUSTOMER_USER_ID = 'customer_user_id'
    COUNTRY_ID = 'country_id'
    CITY_ID = 'city_id'
    BUILDING_ID = 'building_id'
    ROOM_ID = 'room_id'
    RACK_ID = 'rack_id'
    SUPERNET_ID = 'supernet_id'
    SUBNET_ID = 'subnet_id'
    VLAN_ID = 'vlan_id'
    OPERATING_SYSTEM_ID = 'operating_system_id'
    CLIENT_ID = 'client_id'
    MONITOR_ID = 'monitor_id'
    PRINTER_ID = 'printer_id'
    SERVER_ID = 'server_id'
    APPLIANCE_ID = 'appliance_id'
    VIRTUAL_SERVER_ID = 'virtual_server_id'
    SWITCH_ID = 'switch_id'
    ROUTER_ID = 'router_id'
    PATCH_PANEL_ID = 'patch_panel_id'
    WIRELESS_ACCESS_POINT_ID = 'wireless_access_point_id'


class AssistantFieldKey(BaseStrEnum):
    """
    Field-dict keys private to the assistant's intermediate representation

    These keys appear in the field dicts the profiles pass to the ProfileTypeConstructor but are
    not part of the persisted CmdbType field schema (which uses FieldKey). IS_SUMMARY flags a
    field for the type summary; EXTRAS holds the nested extra-property dict; SUMMARIES and
    HELPER_TEXT are extra-property keys not covered by FieldKey
    """
    IS_SUMMARY = 'is_summary'
    EXTRAS = 'extras'
    SUMMARIES = 'summaries'
    HELPER_TEXT = 'helperText'


class AssistantSectionKey(BaseStrEnum):
    """
    Section-dict keys private to the assistant's intermediate representation

    GLOBAL_ID_NAME marks a section sourced from a predefined section template (its template name
    is appended to the type's global_template_ids). CONDITIONAL_IDS carries the list of type-slot
    public_ids a conditional section depends on; the section is only created when all are present
    """
    GLOBAL_ID_NAME = 'global_id_name'
    CONDITIONAL_IDS = 'conditional_ids'


class RenderMetaKey(BaseStrEnum):
    """
    Keys of the CmdbType 'render_meta' sub-dict the ProfileTypeConstructor builds

    ICON holds the type icon, SECTIONS the ordered section layout, EXTERNALS the external-link
    list and SUMMARY the summary-field container (whose own field list lives under FIELDS)
    """
    ICON = 'icon'
    SECTIONS = 'sections'
    EXTERNALS = 'externals'
    SUMMARY = 'summary'
    FIELDS = 'fields'


class TypeDefault:
    """
    Fixed default values written into every CmdbType the assistant creates

    VERSION and AUTHOR_ID are the initial type version and the author the assistant attributes
    created types to. CI_EXPLORER_COLOR_MAX and CI_EXPLORER_COLOR_HEX_WIDTH bound the random
    CI-Explorer color: a value in [0, CI_EXPLORER_COLOR_MAX] rendered as a zero-padded,
    CI_EXPLORER_COLOR_HEX_WIDTH-digit uppercase hex string (a 6-digit '#RRGGBB' color)
    """
    VERSION: str = '1.0.0'
    AUTHOR_ID: int = 1
    CI_EXPLORER_COLOR_MAX: int = 0xFFFFFF
    CI_EXPLORER_COLOR_HEX_WIDTH: int = 6


class RackTypeIdentity:
    """
    The CmdbType identity the 'Rack View' profile assigns to the RACK SpecialType

    NAME is deliberately the same name the location profile gives its basic 'Rack' type: a CmdbType
    name is unique, so only one of the two profiles may create it. The location profile therefore
    only builds its own Rack when the RACK_ID slot is still empty (see LocationProfile.create_profile)
    """
    NAME: str = 'rack'
    LABEL: str = 'Rack'
    ICON: str = 'fas fa-th-large'


class CategoryBodyKey(BaseStrEnum):
    """
    Keys of the CmdbCategory dict the assistant builds after all types are created
    """
    NAME = 'name'
    LABEL = 'label'
    META = 'meta'
    PARENT = 'parent'
    TYPES = 'types'
    CREATION_TIME = 'creation_time'


class CategoryMetaKey(BaseStrEnum):
    """
    Keys of the 'meta' sub-dict of a CmdbCategory built by the assistant
    """
    ICON = 'icon'
    ORDER = 'order'


class CategoryDefinitionKey(BaseStrEnum):
    """
    Keys of a single entry in CATEGORY_DEFINITIONS

    NAME, LABEL and ICON supply the category metadata; TYPE_SLOTS lists the TypeSlotKey members
    whose created types belong to the category
    """
    NAME = 'name'
    LABEL = 'label'
    ICON = 'icon'
    TYPE_SLOTS = 'type_slots'


# The five categories the assistant can create, in display order. A category is only persisted when
# at least one of its TYPE_SLOTS was populated during the run (see ProfileAssistant.get_all_categories)
CATEGORY_DEFINITIONS: list[dict[str, Any]] = [
    {
        CategoryDefinitionKey.NAME: 'contact',
        CategoryDefinitionKey.LABEL: 'Contact',
        CategoryDefinitionKey.ICON: 'fas fa-male',
        CategoryDefinitionKey.TYPE_SLOTS: [
            TypeSlotKey.COMPANY_ID,
            TypeSlotKey.CUSTOMER_USER_ID,
            TypeSlotKey.USER_ID,
        ],
    },
    {
        CategoryDefinitionKey.NAME: 'hardware',
        CategoryDefinitionKey.LABEL: 'Hardware',
        CategoryDefinitionKey.ICON: 'fas fa-hdd',
        CategoryDefinitionKey.TYPE_SLOTS: [
            TypeSlotKey.CLIENT_ID,
            TypeSlotKey.MONITOR_ID,
            TypeSlotKey.PRINTER_ID,
            TypeSlotKey.APPLIANCE_ID,
            TypeSlotKey.RACK_ID,
            TypeSlotKey.SERVER_ID,
        ],
    },
    {
        CategoryDefinitionKey.NAME: 'location',
        CategoryDefinitionKey.LABEL: 'Location',
        CategoryDefinitionKey.ICON: 'fas fa-hotel',
        CategoryDefinitionKey.TYPE_SLOTS: [
            TypeSlotKey.COUNTRY_ID,
            TypeSlotKey.CITY_ID,
            TypeSlotKey.BUILDING_ID,
            TypeSlotKey.ROOM_ID,
        ],
    },
    {
        CategoryDefinitionKey.NAME: 'network',
        CategoryDefinitionKey.LABEL: 'Network',
        CategoryDefinitionKey.ICON: 'fas fa-network-wired',
        CategoryDefinitionKey.TYPE_SLOTS: [
            TypeSlotKey.PATCH_PANEL_ID,
            TypeSlotKey.ROUTER_ID,
            TypeSlotKey.SWITCH_ID,
            TypeSlotKey.WIRELESS_ACCESS_POINT_ID,
            TypeSlotKey.SUPERNET_ID,
            TypeSlotKey.SUBNET_ID,
            TypeSlotKey.VLAN_ID,
        ],
    },
    {
        CategoryDefinitionKey.NAME: 'software',
        CategoryDefinitionKey.LABEL: 'Software',
        CategoryDefinitionKey.ICON: 'far fa-id-card',
        CategoryDefinitionKey.TYPE_SLOTS: [
            TypeSlotKey.OPERATING_SYSTEM_ID,
            TypeSlotKey.VIRTUAL_SERVER_ID,
        ],
    },
]


class IpamSpecialTypeKey(BaseStrEnum):
    """
    Keys of a single entry in IPAM_SPECIAL_TYPE_DEFINITIONS

    SPECIAL_TYPE is the SpecialType marker; SLOT is the TypeSlotKey under which the created type's
    public_id is stored; NAME, LABEL and ICON are the CmdbType identity the assistant assigns (the
    REST/FE creation flow normally lets the user choose these, the assistant hard-codes them)
    """
    SPECIAL_TYPE = 'special_type'
    SLOT = 'slot'
    NAME = 'name'
    LABEL = 'label'
    ICON = 'icon'


# The three IPAM SpecialTypes the ipam-profile creates, in creation order. Order is significant:
# handle_special_types wires each type's reference fields to the already-created ones, so SUPERNET
# must precede SUBNET and SUBNET must precede VLAN. The schemas themselves come from the canonical
# SchemaProvider; only the per-type identity (name/label/icon) is defined here
IPAM_SPECIAL_TYPE_DEFINITIONS: list[dict[str, Any]] = [
    {
        IpamSpecialTypeKey.SPECIAL_TYPE: SpecialType.SUPERNET,
        IpamSpecialTypeKey.SLOT: TypeSlotKey.SUPERNET_ID,
        IpamSpecialTypeKey.NAME: 'supernet',
        IpamSpecialTypeKey.LABEL: 'Supernet',
        IpamSpecialTypeKey.ICON: 'fas fa-sitemap',
    },
    {
        IpamSpecialTypeKey.SPECIAL_TYPE: SpecialType.SUBNET,
        IpamSpecialTypeKey.SLOT: TypeSlotKey.SUBNET_ID,
        IpamSpecialTypeKey.NAME: 'subnet',
        IpamSpecialTypeKey.LABEL: 'Subnet',
        IpamSpecialTypeKey.ICON: 'fas fa-network-wired',
    },
    {
        IpamSpecialTypeKey.SPECIAL_TYPE: SpecialType.VLAN,
        IpamSpecialTypeKey.SLOT: TypeSlotKey.VLAN_ID,
        IpamSpecialTypeKey.NAME: 'vlan',
        IpamSpecialTypeKey.LABEL: 'VLAN',
        IpamSpecialTypeKey.ICON: 'fas fa-wave-square',
    },
]
