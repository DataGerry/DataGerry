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
Constants owned by the `UsersManager`

Currently the read projections. They live here rather than in the manager module so the manager
file stays behaviour only, per the project's `<domain>_constants.py` convention
"""
# -------------------------------------------------------------------------------------------------------------------- #

# Minimal projection for displaying a user (e.g. as a log author) without loading the full document.
# Deliberately omits the password digest, email, api_level and the rest of the account record: every
# consumer of this projection only renders a name and an avatar
MINIMAL_USER_PROJECTION: dict[str, int] = {
    'public_id': 1,
    'first_name': 1,
    'last_name': 1,
    'image': 1,
    'user_name': 1,
    '_id': 0,
}

# Projection for reading only the identifiers of a user set, e.g. to cascade a delete into the
# collections that reference users by public_id
USER_ID_PROJECTION: dict[str, int] = {
    'public_id': 1,
    '_id': 0,
}
