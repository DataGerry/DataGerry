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
Reference guards shared by the CmdbPerson and CmdbPersonGroup routes

Both sides of the person / person-group membership are written by the client as a list of public_ids -
a person names their groups, a group names its members - and both used to be stored without ever
asking whether those ids exist. An unknown id was accepted silently: the document kept it, the
reciprocal ``$addToSet`` matched no document, and the two sides of the membership disagreed from that
moment on, with nothing in the response to say so.

``abort_on_unknown_references`` is the guard both routes run before writing. It costs one projected
``$in`` query (see ``GenericManager.find_existing_public_ids``) and answers 400 naming the ids it could
not find, which is the same shape the rest of the API uses for a payload that points at something that
is not there
"""
from logging import Logger, getLogger
from typing import Iterable

from flask import abort

from cmdb.manager.generic_manager import GenericManager
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

__all__: list[str] = [
    'abort_on_unknown_references',
]


def abort_on_unknown_references(
        manager: GenericManager,
        public_ids: Iterable[int] | None,
        entity_label: str) -> None:
    """
    Refuses the request when a referenced public_id does not exist

    Args:
        manager (GenericManager): The manager owning the referenced collection
        public_ids (Iterable[int] | None): The referenced public_ids; nothing is checked for an empty
                                           or missing selection
        entity_label (str): What the ids refer to, used in the error message (e.g. 'PersonGroup')

    Raises:
        HTTPException: 400 naming every id that does not exist
    """
    referenced: list[int] = list(public_ids or [])

    if not referenced:
        return

    unknown: list[int] = sorted(set(referenced) - manager.find_existing_public_ids(referenced))

    if unknown:
        abort(400, f"The following {entity_label} ID(s) do not exist: {unknown}!")
