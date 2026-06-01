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
Value-contract tripwire for the project's string enums

The string *values* of these (str, Enum) classes are data contracts: they are persisted in
MongoDB (e.g. a CmdbType field's 'type', an extendable option's 'option_type', a log's action)
or used as REST / wire tokens (e.g. the CI Explorer 'target_type', auth scheme, report mds_mode).
Renaming a member or editing a literal would silently desynchronise stored documents and clients,
and nothing else fails loudly when that happens - this module does.

Each enum's full name -> value map is pinned here. Comparing the whole map (not just individual
values) also catches an added, removed or renamed member. The is_valid mechanics are deliberately
NOT retested - they are inherited behaviour covered once in tests/unit/utils/test_base_str_enum.py.

Pure tests: no Mongo, no Flask, no fixtures
"""
from enum import Enum

import pytest

from cmdb.framework.docapi.docapi_template.docgen_header_footer import PageValue, HeaderValue, FooterValue
from cmdb.framework.datagerry_assistant.profile_name import ProfileName
from cmdb.interface.rest_api.auth_method_enum import AuthMethod
from cmdb.models.reports_model.mds_mode_enum import MdsMode
from cmdb.models.log_model.log_interaction_enum import LogInteraction
from cmdb.models.extendable_option_model.option_type_enum import OptionType
from cmdb.models.object_group_model.object_group_mode_enum import ObjectGroupMode
from cmdb.models.object_group_model.object_reference_type_enum import ObjectReferenceType
from cmdb.models.group_model.group_delete_mode_enum import GroupDeleteMode
from cmdb.models.isms_model.control_measure_type_enum import ControlMeasureType
from cmdb.models.isms_model.risk_type_enum import RiskType
from cmdb.models.isms_model.treatment_option_enum import TreatmentOption
from cmdb.models.isms_model.isms_import_type_enum import IsmsImportType
from cmdb.models.docapi_model.docapi_template_type_enum import DocapiTemplateType
from cmdb.models.webhook_model.webhook_event_type_enum import WebhookEventType
from cmdb.models.person_group_model.person_reference_type_enum import PersonReferenceType
from cmdb.models.ci_explorer_model.node_type_enum import NodeType
from cmdb.models.type_model.section_key_enum import SectionKey
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.section_type_enum import SectionType
from cmdb.framework.datagerry_assistant.datagerry_assistant_constants import (
    TypeConfigKey,
    RenderMetaKey,
    CategoryBodyKey,
    CategoryMetaKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

# Pinned member-name -> string-value contract for every string enum whose value crosses a
# persistence or API boundary. Update a row here only as a deliberate, reviewed contract change.
VALUE_CONTRACTS: list[tuple[type[Enum], dict[str, str]]] = [
    (PageValue, {
        'MARGIN_TOP': 'margin-top',
        'MARGIN_BOTTOM': 'margin-bottom',
        'MARGIN_LEFT': 'margin-left',
        'MARGIN_RIGHT': 'margin-right',
        'MAX_WIDTH': 'width',
    }),
    (HeaderValue, {'HEIGHT': 'height'}),
    (FooterValue, {'HEIGHT': 'height'}),
    (ProfileName, {
        'USER_MANAGEMENT': 'user-management-profile',
        'LOCATION': 'location-profile',
        'IPAM': 'ipam-profile',
        'CLIENT_MANAGEMENT': 'client-management-profile',
        'SERVER_MANAGEMENT': 'server-management-profile',
        'NETWORK_INFRASTRUCTURE': 'network-infrastructure-profile',
    }),
    (AuthMethod, {'BASIC': 'Basic', 'JWT': 'JWT'}),
    (MdsMode, {'ROWS': 'ROWS', 'COLUMNS': 'COLUMNS'}),
    (LogInteraction, {'CREATE': 'CREATE', 'EDIT': 'EDIT', 'DELETE': 'DELETE'}),
    (OptionType, {
        'OBJECT_GROUP': 'OBJECT_GROUP',
        'THREAT_VULNERABILITY': 'THREAT_VULNERABILITY',
        'IMPLEMENTATION_STATE': 'IMPLEMENTATION_STATE',
        'CONTROL_MEASURE': 'CONTROL_MEASURE',
        'RISK': 'RISK',
    }),
    (ObjectGroupMode, {'STATIC': 'STATIC', 'DYNAMIC': 'DYNAMIC'}),
    (ObjectReferenceType, {'OBJECT': 'OBJECT', 'OBJECT_GROUP': 'OBJECT_GROUP'}),
    (GroupDeleteMode, {'MOVE': 'MOVE', 'DELETE': 'DELETE'}),
    (ControlMeasureType, {'CONTROL': 'CONTROL', 'REQUIREMENT': 'REQUIREMENT', 'MEASURE': 'MEASURE'}),
    (RiskType, {'THREAT_X_VULNERABILITY': 'THREAT_X_VULNERABILITY', 'THREAT': 'THREAT', 'EVENT': 'EVENT'}),
    (TreatmentOption, {
        'AVOID': 'AVOID',
        'ACCEPT': 'ACCEPT',
        'REDUCE': 'REDUCE',
        'TRANSFER_SHARE': 'TRANSFER_SHARE',
    }),
    (IsmsImportType, {
        'RISK': 'risk',
        'CONTROL_MEASURE': 'control_measure',
        'THREAT': 'threat',
        'VULNERABILITY': 'vulnerability',
    }),
    (DocapiTemplateType, {'OBJECT': 'OBJECT', 'DEFAULT': 'DEFAULT'}),
    (WebhookEventType, {'CREATE': 'CREATE', 'UPDATE': 'UPDATE', 'DELETE': 'DELETE'}),
    (PersonReferenceType, {'PERSON': 'PERSON', 'PERSON_GROUP': 'PERSON_GROUP'}),
    (NodeType, {'CHILD': 'CHILD', 'PARENT': 'PARENT', 'BOTH': 'BOTH'}),
    (SectionKey, {'TYPE': 'type', 'NAME': 'name', 'LABEL': 'label', 'FIELDS': 'fields'}),
    (FieldKey, {
        'TYPE': 'type',
        'NAME': 'name',
        'LABEL': 'label',
        'DESCRIPTION': 'description',
        'REQUIRED': 'required',
        'REGEX': 'regex',
        'REF_TYPES': 'ref_types',
        'OPTIONS': 'options',
    }),
    (FieldType, {
        'TEXT': 'text',
        'NUMBER': 'number',
        'PASSWORD': 'password',
        'TEXTAREA': 'textarea',
        'CHECKBOX': 'checkbox',
        'RADIO': 'radio',
        'SELECT': 'select',
        'DATE': 'date',
        'REFERENCE': 'ref',
        'LOCATION': 'location',
        'REF_SECTION': 'ref-section-field',
    }),
    (SectionType, {'SECTION': 'section', 'MDS_SECTION': 'multi-data-section', 'REF_SECTION': 'ref-section'}),
    # DataGerry assistant key enums whose values are written into persisted CmdbType / CmdbCategory
    # documents (the assistant uses them as dict keys when building those documents)
    (TypeConfigKey, {
        'NAME': 'name',
        'SELECTABLE_AS_PARENT': 'selectable_as_parent',
        'GLOBAL_TEMPLATE_IDS': 'global_template_ids',
        'ACTIVE': 'active',
        'AUTHOR_ID': 'author_id',
        'CREATION_TIME': 'creation_time',
        'EDITOR_ID': 'editor_id',
        'LAST_EDIT_TIME': 'last_edit_time',
        'LABEL': 'label',
        'VERSION': 'version',
        'DESCRIPTION': 'description',
        'RENDER_META': 'render_meta',
        'CI_EXPLORER_LABEL': 'ci_explorer_label',
        'CI_EXPLORER_COLOR': 'ci_explorer_color',
        'PUBLIC_ID': 'public_id',
        'FIELDS': 'fields',
        'ACL': 'acl',
    }),
    (RenderMetaKey, {
        'ICON': 'icon',
        'SECTIONS': 'sections',
        'EXTERNALS': 'externals',
        'SUMMARY': 'summary',
        'FIELDS': 'fields',
    }),
    (CategoryBodyKey, {
        'NAME': 'name',
        'LABEL': 'label',
        'META': 'meta',
        'PARENT': 'parent',
        'TYPES': 'types',
        'CREATION_TIME': 'creation_time',
    }),
    (CategoryMetaKey, {'ICON': 'icon', 'ORDER': 'order'}),
]


# -------------------------------------------------------------------------------------------------------------------- #
#                                              value-contract tripwire                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('enum_cls,expected', VALUE_CONTRACTS, ids=[cls.__name__ for cls, _ in VALUE_CONTRACTS])
def test_string_enum_value_contract_is_pinned(enum_cls: type[Enum], expected: dict[str, str]) -> None:
    """The enum's member name -> value map matches its pinned contract (any drift fails loudly)"""
    assert {member.name: member.value for member in enum_cls} == expected
