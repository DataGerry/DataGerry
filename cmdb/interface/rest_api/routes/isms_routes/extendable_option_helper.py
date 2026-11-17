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
Extendable options the ISMS catalog import needs (control source = catalog title, implementation state)
"""
from cmdb.database import MongoDatabaseManager
from cmdb.models.extendable_option_model import CmdbExtendableOption, ExtendableOptionKey
# -------------------------------------------------------------------------------------------------------------------- #

def get_or_create_extendable_option(
        dbm: MongoDatabaseManager,
        db_name: str | None,
        option_type: str,
        value: str,
    ) -> int:
    """
    public_id of the CmdbExtendableOption (option_type, value), created when it does not exist yet

    Returns:
        int: public_id of the option
    """
    criteria = {
        ExtendableOptionKey.OPTION_TYPE.value: option_type,
        ExtendableOptionKey.VALUE.value: value,
    }

    existing = dbm.find_one_by(CmdbExtendableOption.COLLECTION, db_name, filter=criteria)

    if existing:
        return existing['public_id']

    return dbm.insert(CmdbExtendableOption.COLLECTION, db_name, {
        **criteria,
        ExtendableOptionKey.PREDEFINED.value: False,
    })
