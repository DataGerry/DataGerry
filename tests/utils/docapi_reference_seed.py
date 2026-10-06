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
The seed of the DocAPI reference tests: a root object whose document reads into every kind of reference

* ROOT - a plain reference to MID (two hops: MID references LEAF), a plain reference to HIDDEN, a reference
  section on MID's main section, and a location field NOT named ``dg_location`` (``placement``) pointing at
  LOCATION_NODE_ID
* MID - its own plain reference to LEAF
* LEAF - a name
* HIDDEN - a type only the admin group may read
* DECOY - an object whose public_id is LOCATION_NODE_ID: a location field followed as an object reference would
  read this one instead of the location
* a location node LOCATION_NODE_ID named LOCATION_NAME, a DEFAULT and an OBJECT (legacy) template reading every
  value, and a member of the default user group (who may not read HIDDEN)

Everything is written straight into the collections
"""
from datetime import datetime, timezone
from typing import Any

from cmdb.database import MongoDatabaseManager
from cmdb.framework.docapi.docapi_template.docapi_template import DocapiTemplate
from cmdb.models.docapi_model.docapi_template_type_enum import DocapiTemplateType
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID, USER_GROUP_ID
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.location_model.location_constants import RootLocationDefault
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.section_type_enum import SectionType
from cmdb.models.user_model import CmdbUser
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

ROOT_TYPE_ID: int = 89601
MID_TYPE_ID: int = 89602
LEAF_TYPE_ID: int = 89603
HIDDEN_TYPE_ID: int = 89604

ROOT_ID: int = 89611
MID_ID: int = 89612
LEAF_ID: int = 89613
HIDDEN_ID: int = 89614
LOCATION_NODE_ID: int = 89615
DECOY_ID: int = LOCATION_NODE_ID

DEFAULT_TEMPLATE_ID: int = 89621
OBJECT_TEMPLATE_ID: int = 89622
USER_ID: int = 89631
USER_NAME: str = 'docapi-reference-user'

NAME_FIELD: str = 'dg_name'
MID_REF: str = 'mid-ref'
LEAF_REF: str = 'leaf-ref'
HIDDEN_REF: str = 'hidden-ref'
SECTION_NAME: str = 'main'
REF_SECTION: str = 'ms'
REF_SECTION_FIELD: str = f'{REF_SECTION}-field'
PLACEMENT_FIELD: str = 'placement'

ROOT_VALUE: str = 'docref-root-value'
MID_VALUE: str = 'docref-mid-value'
LEAF_VALUE: str = 'docref-leaf-value'
HIDDEN_VALUE: str = 'docref-hidden-value'
DECOY_VALUE: str = 'docref-decoy-value'
LOCATION_NAME: str = 'docref-location-name'

ALL_TYPE_IDS: list[int] = [ROOT_TYPE_ID, MID_TYPE_ID, LEAF_TYPE_ID, HIDDEN_TYPE_ID]
ALL_OBJECT_IDS: list[int] = [ROOT_ID, MID_ID, LEAF_ID, HIDDEN_ID, DECOY_ID]
ALL_TEMPLATE_IDS: list[int] = [DEFAULT_TEMPLATE_ID, OBJECT_TEMPLATE_ID]

# Every value, between markers so a test can tell them apart in the document: the root's own name, the first hop,
# the second hop, the hidden reference, the reference section, the location field, and object(<MID>)'s reference
DEFAULT_TEMPLATE_BODY: str = (
    f"<p>ROOT[{{{{ root.fields.{NAME_FIELD} }}}}]</p>"
    f"<p>HOP1[{{{{ root.fields['{MID_REF}'].fields.{NAME_FIELD} }}}}]</p>"
    f"<p>HOP2[{{{{ root.fields['{MID_REF}'].fields['{LEAF_REF}'].fields.{NAME_FIELD} }}}}]</p>"
    f"<p>HIDDEN[{{{{ root.fields['{HIDDEN_REF}'].fields.{NAME_FIELD} }}}}]</p>"
    f"<p>SECTION[{{{{ root.fields['{REF_SECTION_FIELD}'].fields.{NAME_FIELD} }}}}]</p>"
    f"<p>PLACE[{{{{ root.fields.{PLACEMENT_FIELD} }}}}]</p>"
    f"<p>OBJECT[{{{{ object({MID_ID}).fields['{LEAF_REF}'].fields.{NAME_FIELD} }}}}]</p>"
)
OBJECT_TEMPLATE_BODY: str = (
    f"<p>ROOT[{{{{ fields.{NAME_FIELD} }}}}]</p>"
    f"<p>HOP1[{{{{ fields['{MID_REF}'].fields.{NAME_FIELD} }}}}]</p>"
    f"<p>HOP2[{{{{ fields['{MID_REF}'].fields['{LEAF_REF}'].fields.{NAME_FIELD} }}}}]</p>"
    f"<p>SECTION[{{{{ fields['{REF_SECTION_FIELD}'].fields.{NAME_FIELD} }}}}]</p>"
    f"<p>PLACE[{{{{ fields.{PLACEMENT_FIELD} }}}}]</p>"
)


def marked(marker: str, value: str = '') -> str:
    """What the document shows between a marker's brackets."""
    return f'{marker}[{value}]'


def _name() -> dict[str, Any]:
    """The name field definition."""
    return {'type': FieldType.TEXT.value, 'name': NAME_FIELD, 'label': 'Name'}


def _reference(name: str, type_id: int) -> dict[str, Any]:
    """A plain reference field definition."""
    return {'type': FieldType.REFERENCE.value, 'name': name, 'label': name, 'ref_types': [type_id]}


def _main(*fields: str) -> dict[str, Any]:
    """A plain section listing `fields`."""
    return {'type': SectionType.SECTION.value, 'name': SECTION_NAME, 'label': 'Main', 'fields': list(fields)}


def _type_docs() -> list[dict[str, Any]]:
    """ROOT, MID, LEAF and HIDDEN; only HIDDEN carries an ACL, granting READ to the admin group alone."""
    root = make_type_doc(
        ROOT_TYPE_ID, 'docref-root',
        fields=[
            _name(), _reference(MID_REF, MID_TYPE_ID), _reference(HIDDEN_REF, HIDDEN_TYPE_ID),
            {'type': FieldType.REF_SECTION.value, 'name': REF_SECTION_FIELD, 'label': REF_SECTION,
             'ref_types': [MID_TYPE_ID]},
            {'type': FieldType.LOCATION.value, 'name': PLACEMENT_FIELD, 'label': 'Placement'},
        ],
        sections=[
            _main(NAME_FIELD, MID_REF, HIDDEN_REF, PLACEMENT_FIELD),
            {'type': SectionType.REF_SECTION.value, 'name': REF_SECTION, 'label': REF_SECTION,
             'fields': [REF_SECTION_FIELD],
             'reference': {'type_id': MID_TYPE_ID, 'section_name': SECTION_NAME, 'selected_fields': []}},
        ],
    )
    mid = make_type_doc(MID_TYPE_ID, 'docref-mid', fields=[_name(), _reference(LEAF_REF, LEAF_TYPE_ID)],
                        sections=[_main(NAME_FIELD, LEAF_REF)])
    leaf = make_type_doc(LEAF_TYPE_ID, 'docref-leaf', fields=[_name()], sections=[_main(NAME_FIELD)])
    hidden = make_type_doc(HIDDEN_TYPE_ID, 'docref-hidden', fields=[_name()], sections=[_main(NAME_FIELD)])
    hidden['acl'] = {'activated': True, 'groups': {'includes': {str(ADMIN_GROUP_ID): ['READ']}}}

    return [root, mid, leaf, hidden]


def _object_doc(public_id: int, type_id: int, value: str, *extra: dict[str, Any]) -> dict[str, Any]:
    """A complete CmdbObject document named `value`."""
    return {
        'public_id': public_id, 'type_id': type_id, 'active': True, 'author_id': 1, 'version': '1.0.0',
        'creation_time': datetime.now(timezone.utc), 'multi_data_sections': [],
        'fields': [{'type': FieldType.TEXT.value, 'name': NAME_FIELD, 'value': value}, *extra],
    }


def _stored(field_type: FieldType, name: str, value: Any) -> dict[str, Any]:
    """A stored field entry."""
    return {'type': field_type.value, 'name': name, 'value': value}


def _template_doc(public_id: int, template_type: DocapiTemplateType, body: str) -> dict[str, Any]:
    """An active DocAPI template of `template_type`."""
    return {
        'public_id': public_id, 'name': f'docref-{public_id}', 'label': f'Doc refs {public_id}', 'active': True,
        'author_id': 1, 'template_type': template_type.value, 'template_data': body, 'template_style': '',
    }


def seed(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Writes the types, the objects, the location node, the two templates and the default-group user."""
    purge(database_manager, database_name)
    database_manager.get_collection(CmdbType.COLLECTION, database_name).insert_many(_type_docs())
    database_manager.get_collection(CmdbObject.COLLECTION, database_name).insert_many([
        _object_doc(ROOT_ID, ROOT_TYPE_ID, ROOT_VALUE,
                    _stored(FieldType.REFERENCE, MID_REF, MID_ID),
                    _stored(FieldType.REFERENCE, HIDDEN_REF, HIDDEN_ID),
                    _stored(FieldType.REF_SECTION, REF_SECTION_FIELD, MID_ID),
                    _stored(FieldType.LOCATION, PLACEMENT_FIELD, LOCATION_NODE_ID)),
        _object_doc(MID_ID, MID_TYPE_ID, MID_VALUE, _stored(FieldType.REFERENCE, LEAF_REF, LEAF_ID)),
        _object_doc(LEAF_ID, LEAF_TYPE_ID, LEAF_VALUE),
        _object_doc(HIDDEN_ID, HIDDEN_TYPE_ID, HIDDEN_VALUE),
        _object_doc(DECOY_ID, LEAF_TYPE_ID, DECOY_VALUE),
    ])
    database_manager.get_collection(CmdbLocation.COLLECTION, database_name).insert_one({
        'public_id': LOCATION_NODE_ID, 'name': LOCATION_NAME, 'parent': RootLocationDefault.PUBLIC_ID,
        'object_id': ROOT_ID, 'type_id': ROOT_TYPE_ID, 'type_label': 'docref-root', 'type_icon': 'fa-cube',
        'type_selectable': True,
    })
    database_manager.get_collection(DocapiTemplate.COLLECTION, database_name).insert_many([
        _template_doc(DEFAULT_TEMPLATE_ID, DocapiTemplateType.DEFAULT, DEFAULT_TEMPLATE_BODY),
        _template_doc(OBJECT_TEMPLATE_ID, DocapiTemplateType.OBJECT, OBJECT_TEMPLATE_BODY),
    ])
    database_manager.get_collection(CmdbUser.COLLECTION, database_name).insert_one({
        'public_id': USER_ID, 'user_name': USER_NAME, 'active': True, 'group_id': USER_GROUP_ID,
        'registration_time': datetime.now(timezone.utc),
    })


def purge(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Removes everything `seed` wrote."""
    database_manager.get_collection(CmdbType.COLLECTION, database_name).delete_many(
        {'public_id': {'$in': ALL_TYPE_IDS}})
    database_manager.get_collection(CmdbObject.COLLECTION, database_name).delete_many(
        {'public_id': {'$in': ALL_OBJECT_IDS}})
    database_manager.get_collection(CmdbLocation.COLLECTION, database_name).delete_many(
        {'public_id': LOCATION_NODE_ID})
    database_manager.get_collection(DocapiTemplate.COLLECTION, database_name).delete_many(
        {'public_id': {'$in': ALL_TEMPLATE_IDS}})
    database_manager.get_collection(CmdbUser.COLLECTION, database_name).delete_many({'public_id': USER_ID})


def default_user() -> CmdbUser:
    """The seeded member of the default user group - holds object view, may not read HIDDEN."""
    return CmdbUser(public_id=USER_ID, user_name=USER_NAME, active=True, group_id=USER_GROUP_ID)
