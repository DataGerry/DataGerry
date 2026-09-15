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
This module contains the DocapiTemplateKey Enumeration
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

class DocapiTemplateKey(BaseStrEnum):
    """Serialization keys of a DocapiTemplate document (used by from_data / to_json)."""
    PUBLIC_ID = "public_id"
    NAME = "name"
    LABEL = "label"
    DESCRIPTION = "description"
    ACTIVE = "active"
    AUTHOR_ID = "author_id"
    TEMPLATE_DATA = "template_data"
    TEMPLATE_STYLE = "template_style"
    TEMPLATE_TYPE = "template_type"
    TEMPLATE_PARAMETERS = "template_parameters"
    HEADER = "header"
    FOOTER = "footer"
    TABLE_OF_CONTENTS = "table_of_contents"
    COVER_PAGE = "cover_page"
    PAGE_CONFIG = "page_config"
