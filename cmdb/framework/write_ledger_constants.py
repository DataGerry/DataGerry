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
The names a WriteLedger records its writes and reports its residue under
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #


class WriteKind(BaseStrEnum):
    """What a recorded write did, which decides how it is undone"""
    # One document inserted under a known public_id: undone by deleting it
    INSERT = 'insert'
    # A batch inserted where the failure may not report which documents made it: undone by deleting every
    # document the recorded criteria match
    INSERT_BATCH = 'insert_batch'
    # One document changed: undone by replacing it with its prior snapshot
    UPDATE = 'update'
    # One document deleted: undone by re-inserting its prior snapshot under its old id
    DELETE = 'delete'
    # A write with an inverse of its own, where a snapshot restore would do more than undo it (e.g. put a
    # whole document back when the write changed one field): undone by the recorded callable, checked by the
    # recorded verification
    COMPENSATED = 'compensated'


class LedgerResidueKey(BaseStrEnum):
    """The keys of one residue entry, as a refusal names it to the caller"""
    COLLECTION = 'collection'
    KIND = 'kind'
    PUBLIC_ID = 'public_id'
    CRITERIA = 'criteria'
    DESCRIPTION = 'description'
