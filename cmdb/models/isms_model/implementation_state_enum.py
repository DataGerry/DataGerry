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
The predefined IMPLEMENTATION_STATE option values of ISMS

A risk assessment's ``implementation_status`` holds the public_id of a ``CmdbExtendableOption`` of the
``IMPLEMENTATION_STATE`` type, and four of those are seeded with the database
(``predefined_data/isms_data/isms_extendable_options.py``). Their VALUES are named here because two
places have to agree on them: the seeding that writes them, and the risk-matrix report, which asks
"is this assessment implemented?" by looking the IMPLEMENTED option up by value.

That lookup is why these are constants rather than literals. Re-spelling `'Implemented'` in the report
meant a renamed option answered `None`, and the current-state matrix then silently showed every
assessment's before-treatment values instead of its after-treatment ones - a wrong report with no
error anywhere. A customer may add further states; only these four are predefined
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'ImplementationState',
]


class ImplementationState(BaseStrEnum):
    """The values of the four predefined IMPLEMENTATION_STATE CmdbExtendableOptions"""
    NONE = 'None'
    OPEN = 'Open'
    IN_PROGRESS = 'In Progress'
    IMPLEMENTED = 'Implemented'
