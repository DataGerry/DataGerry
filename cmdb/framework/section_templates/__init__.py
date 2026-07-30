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
Everything about the predefined ("global") section templates DataGerry ships with

    section_template_creator.py     builds the predefined templates the first-boot seeding inserts
    predefined_section_guard.py     names the CmdbType fields a predefined template owns, so the
                                    write paths that edit field definitions can skip / reject them
"""
from .section_template_creator import SectionTemplateCreator
from .predefined_section_guard import (
    PREDEFINED_SELECT_OPTION_REJECTED,
    get_predefined_template_names,
    predefined_select_fields,
    resolve_predefined_select_fields,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'SectionTemplateCreator',
    'PREDEFINED_SELECT_OPTION_REJECTED',
    'get_predefined_template_names',
    'predefined_select_fields',
    'resolve_predefined_select_fields',
]
