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
The single entry point for every feature's un-bypassable CmdbObject write invariants

Both object write paths (apply_object_insert and apply_object_update, the latter also serving the
PATCH and bulk-update routes) call one function here instead of one per feature, so a new feature with
write invariants is wired in once, in this module, rather than in every write path.

Each feature keeps its own validators, its own message wording and its own abort formatter - a Rack
problem must not be reported to the user under the IPAM feature's name - which is why this module
returns a ready-formatted message rather than a merged error list: the errors are formatted by the
feature that produced them, then joined. Feature validators also canonicalise the candidate in place,
so this must be called before the document is persisted.
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.manager import ObjectsManager, TypesManager

from cmdb.framework.ipam.enforcement import enforce_object_invariants, format_errors_for_abort
from cmdb.framework.rack.enforcement import enforce_rack_object_invariants, format_rack_errors_for_abort
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# Separator between the per-feature messages when more than one feature rejected the candidate
FEATURE_ERROR_SEPARATOR: str = ' | '

# -------------------------------------------------------------------------------------------------------------------- #

def enforce_object_write_invariants(
        objects_manager: ObjectsManager,
        types_manager: TypesManager,
        candidate_object: dict[str, Any],
        previous_object: dict[str, Any] | None = None) -> str | None:
    """
    Runs every feature's write invariants against the candidate and returns the abort message

    Currently IPAM (SpecialType objects plus dg-ipam-interface rows on any object) and Rack. Both
    normalise the candidate in place before validating, so the caller must pass the very dict it is
    about to persist. Each feature's errors are formatted by that feature, so the message names the
    feature the user actually tripped over; when several features reject the same candidate their
    messages are joined

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        candidate_object (dict[str, Any]): The about-to-be-saved CmdbObject document
        previous_object (dict[str, Any] | None): The pre-edit document on update; None on insert

    Returns:
        str | None: The formatted abort message, or None when the candidate is valid
    """
    messages: list[str] = []

    ipam_errors: list[dict[str, Any]] = enforce_object_invariants(
        objects_manager,
        types_manager,
        candidate_object,
        previous_object=previous_object,
    )

    if ipam_errors:
        messages.append(format_errors_for_abort(ipam_errors))

    rack_errors: list[dict[str, Any]] = enforce_rack_object_invariants(types_manager, candidate_object)

    if rack_errors:
        messages.append(format_rack_errors_for_abort(rack_errors))

    if not messages:
        return None

    return FEATURE_ERROR_SEPARATOR.join(messages)
