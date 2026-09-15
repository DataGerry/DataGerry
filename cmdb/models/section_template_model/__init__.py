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
Provides all CmdbSectionTemplate relevant classes

A CmdbSectionTemplate is a reusable section definition. A *global* template (``is_global``) is shared
by every CmdbType that references it by name in ``global_template_ids``; a *predefined* template
(``predefined``) is additionally DataGerry-provided and immutable - see
``cmdb.framework.section_templates``
"""
from .cmdb_section_template import CmdbSectionTemplate
from .section_template_constants import SectionTemplateKey, SectionTemplateRight
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'CmdbSectionTemplate',
    'SectionTemplateKey',
    'SectionTemplateRight',
]
