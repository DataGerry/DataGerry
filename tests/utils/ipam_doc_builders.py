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
Shared document builders for the IPAM integration / functional test seeds

The IPAM test modules seed CmdbType / CmdbObject documents directly into the collections;
these builders provide the minimal valid document shapes so every module pins the same
baseline instead of copying it. Builders return plain dicts ready for insert_many
"""
from datetime import datetime, timezone
from typing import Any

from cmdb.models.object_model import CmdbObjectKey, CmdbObjectFieldKey
# -------------------------------------------------------------------------------------------------------------------- #


def make_field(name: str, value: Any) -> dict[str, Any]:
    """
    Builds one stored CmdbObject 'fields' entry / MDS row 'data' entry

    Args:
        name (str): The field name
        value (Any): The stored value

    Returns:
        dict[str, Any]: {'name': ..., 'value': ...}
    """
    return {CmdbObjectFieldKey.NAME: name, CmdbObjectFieldKey.VALUE: value}


def make_type_doc(
    public_id: int,
    name: str,
    special_type: str | None = None,
    fields: list[dict[str, Any]] | None = None,
    sections: list[dict[str, Any]] | None = None,
    global_template_ids: list[str] | None = None,
) -> dict[str, Any]:
    """
    Builds a minimal active CmdbType document for direct collection seeding

    Args:
        public_id (int): The type's public_id
        name (str): Used as both 'name' and 'label'
        special_type (str | None): SpecialType marker ('' when None)
        fields (list[dict[str, Any]] | None): Field definitions; defaults to one dg-name text
        sections (list[dict[str, Any]] | None): render_meta section layout entries
        global_template_ids (list[str] | None): Names of global section templates the type uses

    Returns:
        dict[str, Any]: The CmdbType document
    """
    return {
        CmdbObjectKey.PUBLIC_ID: public_id,
        'name': name,
        'label': name,
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'fields': fields if fields is not None else [{'type': 'text', 'name': 'dg-name', 'label': 'Name'}],
        'render_meta': {
            'icon': 'fa-cube',
            'sections': sections or [],
            'summary': {'fields': ['dg-name']},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': '1.0.0',
        'special_type': special_type if special_type is not None else '',
        'global_template_ids': global_template_ids or [],
    }


def make_object_doc(
    public_id: int,
    type_id: int,
    fields: list[dict[str, Any]],
    mds: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Builds a minimal active CmdbObject document for direct collection seeding

    Args:
        public_id (int): The object's public_id
        type_id (int): public_id of the owning CmdbType
        fields (list[dict[str, Any]]): Stored field entries (see make_field)
        mds (list[dict[str, Any]] | None): multi_data_sections list; omitted when None

    Returns:
        dict[str, Any]: The CmdbObject document
    """
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
