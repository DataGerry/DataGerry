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
Shared constants for the DocapiTemplate REST routes

Names the ACL rights guarding the DocapiTemplate routes so the routes reference enum members
instead of repeating the literal right strings, the media type and file extension the render
route answers a rendered document with, the query parameters the template list reads besides its
collection parameters, and the messages the routes answer with.
"""
from cmdb.utils import BaseStrEnum
from cmdb.models.right_model.right_constants import ObjectRightName
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'RENDER_OBJECT_DENIED_MSG',
    'RENDER_OBJECT_MISSING_MSG',
    'RENDER_OBJECT_NOT_READABLE_MSG',
    'RENDER_OBJECT_RIGHT',
    'RENDER_TEMPLATE_DEACTIVATED_MSG',
    'RENDERED_DOCUMENT_MIMETYPE',
    'RENDERED_DOCUMENT_EXTENSION',
    'DocapiTemplateRight',
    'TemplateListParam',
    'TEMPLATE_DELETE_FAILED_MSG',
    'TEMPLATE_MISSING_MSG',
    'TEMPLATE_NOT_READABLE_MSG',
    'TEMPLATE_RENAME_REFUSED_MSG',
    'TEMPLATE_UPDATE_FAILED_MSG',
    'TYPE_ID_INVALID_MSG',
]

# What the render route answers with. A DocapiTemplate is HTML, but it is rendered to PDF before it
# leaves the route, so the media type and the extension of the download are both fixed here
RENDERED_DOCUMENT_MIMETYPE: str = 'application/pdf'
RENDERED_DOCUMENT_EXTENSION: str = 'pdf'

RENDER_OBJECT_RIGHT: str = ObjectRightName.VIEW.value
"""
The object half of the two rights guarding the render route

A render reads two things and answers both: the template, in full, and the target CmdbObject's field
values. So it requires the right of each - this one for the object, and `DocapiTemplateRight.VIEW` for the
template. Holding either alone is not enough
"""


#: What the render route answers for a template whose `active` flag is off
RENDER_TEMPLATE_DEACTIVATED_MSG: str = 'The Template with ID: {public_id} is deactivated and can not be rendered!'


#: What the render route answers a caller whose group may not READ the object's type
RENDER_OBJECT_DENIED_MSG: str = 'No permission to render the Object with ID: {object_id}!'


#: What the render route answers when its object does not exist
RENDER_OBJECT_MISSING_MSG: str = 'Object with ID: {object_id} for Template with ID: {public_id} not found!'


#: What the render route answers when the read of its object fails
RENDER_OBJECT_NOT_READABLE_MSG: str = 'Could not retrieve the Object with ID: {object_id}!'


#: What the routes by id answer when no template carries the id, or it was deleted before the write reached it
TEMPLATE_MISSING_MSG: str = 'Template with ID: {public_id} not found!'


#: What the routes answer when the read of the addressed template fails
TEMPLATE_NOT_READABLE_MSG: str = 'Could not retrieve the requested template!'


#: What the update route answers when its write fails
TEMPLATE_UPDATE_FAILED_MSG: str = 'Could not update the template!'


#: What the delete route answers when its write fails
TEMPLATE_DELETE_FAILED_MSG: str = 'Could not delete the template!'


#: What the update route answers a payload that would rename the stored template
TEMPLATE_RENAME_REFUSED_MSG: str = ("The 'name' of a template is not changable - '{stored_name}' can not be renamed "
                                    "to '{sent_name}'!")


class DocapiTemplateRight(BaseStrEnum):
    """
    ACL right identifiers guarding the DocapiTemplate REST routes
    """
    ADD = 'base.docapi.template.add'
    VIEW = 'base.docapi.template.view'
    EDIT = 'base.docapi.template.edit'
    DELETE = 'base.docapi.template.delete'


class TemplateListParam(BaseStrEnum):
    """
    Query parameters of ``GET /docapi/template/`` besides its collection parameters

    TYPE_ID: only the templates for objects of this CmdbType (``template_parameters.type``), a positive integer.
    ACTIVE: ``true`` only the templates the render accepts (stored ``true``, ``null`` or no flag at all), ``false``
    only the deactivated ones; absent, both. MINIMAL: ``true`` answers each template as ``{public_id, label}`` only
    (default false)
    """
    TYPE_ID = 'type_id'
    ACTIVE = 'active'
    MINIMAL = 'minimal'


#: What the template list answers for a ``type_id`` that is not a positive integer
TYPE_ID_INVALID_MSG: str = "The parameter 'type_id' must be a positive integer, got: '{value}'!"
