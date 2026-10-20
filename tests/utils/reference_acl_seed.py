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
The seed of the render's reference-ACL tests: an object that references an object the default user group
may not read, in every way a render resolves a reference

* MAIN (visible type) - a plain reference to HIDDEN, a reference section on HIDDEN, a reference section on
  MID, and a reference section that is unset
* MID (visible type) - its own reference-section field points at HIDDEN, so MAIN's section on MID leads
  to HIDDEN through a nested reference section
* HIDDEN (a type only the admin group may read) - carries HIDDEN_VALUE, the value that must never reach a
  render for the default user group

Two users may not read HIDDEN: a member of the default user group, and an EXPORTER whose group holds the
object export right alone - the default group may not export. The ids are written straight into the
collections, so the tests can render or request them as they like
"""
from datetime import datetime, timezone
from typing import Any

from cmdb.database import MongoDatabaseManager
from cmdb.interface.rest_api.routes.exporter_routes.exporter_constants import ExporterRight
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID, USER_GROUP_ID
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.section_type_enum import SectionType
from cmdb.models.user_model import CmdbUser
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

MAIN_TYPE_ID: int = 89301
MID_TYPE_ID: int = 89302
HIDDEN_TYPE_ID: int = 89303

MAIN_ID: int = 89311
MID_ID: int = 89312
HIDDEN_ID: int = 89313
SECOND_MAIN_ID: int = 89314

USER_ID: int = 89321
USER_NAME: str = 'render-reference-acl'
EXPORTER_ID: int = 89322
EXPORTER_NAME: str = 'render-reference-acl-exporter'
EXPORTER_GROUP_ID: int = 89331

NAME_FIELD: str = 'dg_name'
REF_FIELD: str = 'hidden-ref'
SECTION_NAME: str = 'main'
HIDDEN_SECTION: str = 'hid'
MID_SECTION: str = 'mid'
UNSET_SECTION: str = 'unset'
NESTED_SECTION: str = 'hs'

MAIN_VALUE: str = 'main-render-value'
MID_VALUE: str = 'mid-render-value'
HIDDEN_VALUE: str = 'hidden-render-value'
DEFAULT_VALUE: str = 'the-type-default-proposal'

ALL_TYPE_IDS: list[int] = [MAIN_TYPE_ID, MID_TYPE_ID, HIDDEN_TYPE_ID]
ALL_OBJECT_IDS: list[int] = [MAIN_ID, MID_ID, HIDDEN_ID, SECOND_MAIN_ID]


def section_field(section_name: str) -> str:
    """The implicit field a reference section stores its reference in."""
    return f'{section_name}-field'


def _ref_section(name: str, type_id: int) -> dict[str, Any]:
    """A reference section pulling every field of `type_id`'s main section."""
    return {
        'type': SectionType.REF_SECTION.value, 'name': name, 'label': name,
        'reference': {'type_id': type_id, 'section_name': SECTION_NAME, 'selected_fields': []}, 'fields': [],
    }


def _ref_section_field(section_name: str, type_id: int) -> dict[str, Any]:
    """The type's definition of a reference section's implicit field."""
    return {'type': FieldType.REF_SECTION.value, 'name': section_field(section_name), 'label': section_name,
            'ref_types': [type_id]}


def _text(value: str) -> dict[str, Any]:
    """The stored name entry."""
    return {'type': FieldType.TEXT.value, 'name': NAME_FIELD, 'value': value}


def _link(section_name: str, target_id: int | None) -> dict[str, Any]:
    """A stored reference-section entry pointing at `target_id`."""
    return {'type': FieldType.REF_SECTION.value, 'name': section_field(section_name), 'value': target_id}


def _type_docs() -> list[dict[str, Any]]:
    """MAIN, MID and HIDDEN; only HIDDEN carries an ACL, granting READ to the admin group alone."""
    name: dict[str, Any] = {'type': FieldType.TEXT.value, 'name': NAME_FIELD, 'label': 'Name'}
    defaulted_name: dict[str, Any] = {**name, 'value': DEFAULT_VALUE}

    main = make_type_doc(
        MAIN_TYPE_ID, 'render-acl-main',
        fields=[
            name,
            {'type': FieldType.REFERENCE.value, 'name': REF_FIELD, 'label': 'Ref', 'ref_types': [HIDDEN_TYPE_ID]},
            _ref_section_field(HIDDEN_SECTION, HIDDEN_TYPE_ID),
            _ref_section_field(MID_SECTION, MID_TYPE_ID),
            _ref_section_field(UNSET_SECTION, MID_TYPE_ID),
        ],
        sections=[
            {'type': SectionType.SECTION.value, 'name': SECTION_NAME, 'label': 'Main',
             'fields': [NAME_FIELD, REF_FIELD]},
            _ref_section(HIDDEN_SECTION, HIDDEN_TYPE_ID),
            _ref_section(MID_SECTION, MID_TYPE_ID),
            _ref_section(UNSET_SECTION, MID_TYPE_ID),
        ],
    )
    # MID's main section lists its own reference-section field, so a section pulling MID's main section
    # follows it into a nested render of HIDDEN. Its name field proposes a default, which an unset
    # section on MID must not answer as a value
    mid = make_type_doc(
        MID_TYPE_ID, 'render-acl-mid',
        fields=[defaulted_name, _ref_section_field(NESTED_SECTION, HIDDEN_TYPE_ID)],
        sections=[
            {'type': SectionType.SECTION.value, 'name': SECTION_NAME, 'label': 'Main',
             'fields': [NAME_FIELD, section_field(NESTED_SECTION)]},
            _ref_section(NESTED_SECTION, HIDDEN_TYPE_ID),
        ],
    )
    # HIDDEN declares the same reference section, which is what the nested render draws its values from
    hidden = make_type_doc(
        HIDDEN_TYPE_ID, 'render-acl-hidden',
        fields=[name, _ref_section_field(NESTED_SECTION, HIDDEN_TYPE_ID)],
        sections=[
            {'type': SectionType.SECTION.value, 'name': SECTION_NAME, 'label': 'Main', 'fields': [NAME_FIELD]},
            _ref_section(NESTED_SECTION, HIDDEN_TYPE_ID),
        ],
    )
    hidden['acl'] = {'activated': True, 'groups': {'includes': {str(ADMIN_GROUP_ID): ['READ']}}}

    return [main, mid, hidden]


def _object_doc(public_id: int, type_id: int, fields: list[dict[str, Any]]) -> dict[str, Any]:
    """A complete CmdbObject document for direct insertion."""
    return {
        'public_id': public_id, 'type_id': type_id, 'active': True, 'author_id': 1, 'version': '1.0.0',
        'creation_time': datetime.now(timezone.utc), 'fields': fields, 'multi_data_sections': [],
    }


def _main_fields(value: str) -> list[dict[str, Any]]:
    """A MAIN object's stored fields: every way of referencing HIDDEN, and an unset section."""
    return [
        _text(value),
        {'type': FieldType.REFERENCE.value, 'name': REF_FIELD, 'value': HIDDEN_ID},
        _link(HIDDEN_SECTION, HIDDEN_ID),
        _link(MID_SECTION, MID_ID),
        _link(UNSET_SECTION, None),
    ]


def _user_doc(public_id: int, user_name: str, group_id: int) -> dict[str, Any]:
    """An active CmdbUser document."""
    return {'public_id': public_id, 'user_name': user_name, 'active': True, 'group_id': group_id,
            'registration_time': datetime.now(timezone.utc)}


def seed(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Writes the three types, the four objects, the exporter group and the two users."""
    purge(database_manager, database_name)
    database_manager.get_collection(CmdbType.COLLECTION, database_name).insert_many(_type_docs())
    database_manager.get_collection(CmdbObject.COLLECTION, database_name).insert_many([
        _object_doc(MAIN_ID, MAIN_TYPE_ID, _main_fields(MAIN_VALUE)),
        _object_doc(SECOND_MAIN_ID, MAIN_TYPE_ID, _main_fields(MAIN_VALUE)),
        _object_doc(MID_ID, MID_TYPE_ID, [_text(MID_VALUE), _link(NESTED_SECTION, HIDDEN_ID)]),
        _object_doc(HIDDEN_ID, HIDDEN_TYPE_ID, [_text(HIDDEN_VALUE), _link(NESTED_SECTION, None)]),
    ])
    database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name).insert_one({
        'public_id': EXPORTER_GROUP_ID, 'name': EXPORTER_NAME, 'label': EXPORTER_NAME,
        'rights': [ExporterRight.OBJECT.value],
    })
    database_manager.get_collection(CmdbUser.COLLECTION, database_name).insert_many([
        _user_doc(USER_ID, USER_NAME, USER_GROUP_ID), _user_doc(EXPORTER_ID, EXPORTER_NAME, EXPORTER_GROUP_ID),
    ])


def purge(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Removes everything `seed` wrote."""
    database_manager.get_collection(CmdbType.COLLECTION, database_name).delete_many(
        {'public_id': {'$in': ALL_TYPE_IDS}})
    database_manager.get_collection(CmdbObject.COLLECTION, database_name).delete_many(
        {'public_id': {'$in': ALL_OBJECT_IDS}})
    database_manager.get_collection(CmdbUser.COLLECTION, database_name).delete_many(
        {'public_id': {'$in': [USER_ID, EXPORTER_ID]}})
    database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name).delete_many(
        {'public_id': EXPORTER_GROUP_ID})


def default_user() -> CmdbUser:
    """The seeded member of the default 'user' group - may read MAIN and MID, not HIDDEN."""
    return CmdbUser(public_id=USER_ID, user_name=USER_NAME, active=True, group_id=USER_GROUP_ID)


def exporter_user() -> CmdbUser:
    """The seeded exporter - may export objects, may not read HIDDEN."""
    return CmdbUser(public_id=EXPORTER_ID, user_name=EXPORTER_NAME, active=True, group_id=EXPORTER_GROUP_ID)


def load(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> CmdbObject:
    """Reads one seeded object."""
    collection = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    return CmdbObject.from_data(collection.find_one({'public_id': public_id}))
