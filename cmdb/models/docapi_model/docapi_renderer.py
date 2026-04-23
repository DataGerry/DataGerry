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
Implementation of the DocApiRenderer in DataGerry
"""
from logging import Logger, getLogger
from io import BytesIO

from cmdb.framework.rendering.render_result import RenderResult
from cmdb.manager import ObjectsManager

from cmdb.models.object_model import CmdbObject
from cmdb.models.user_model import CmdbUser
from cmdb.models.docapi_model.object_document_generator import ObjectDocumentGenerator
from cmdb.models.docapi_model.pdf_document_type import PdfDocumentType

# from cmdb.framework.rendering.cmdb_render import CmdbRender
from cmdb.framework.rendering.cmdb_multi_render import CmdbMultiRender
from cmdb.framework.docapi.docapi_template.docapi_template import DocapiTemplate
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                DocApiRenderer - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class DocApiRenderer:
    """
     A renderer for generating documents from CmdbObjects using predefined templates
    """

    def __init__(
        self,
        objects_manager: ObjectsManager,
        target_template: DocapiTemplate,
        target_object: CmdbObject,
    ) -> None:
        """
        Initializes the DocApiRenderer

        Args:
            objects_manager (ObjectsManager): The manager responsible for CmdbObjects
            template (DocapiTemplate): Target template
        """
        self.target_template: DocapiTemplate = target_template
        self.target_object: CmdbObject = target_object
        self.objects_manager: ObjectsManager = objects_manager


    def render_object_template(self, request_user: CmdbUser = None) -> BytesIO:
        """
        Renders a document by applying the provided DocapiTemplate to a CmdbObject

        This method retrieves the DocapiTemplate and the CmdbObject using their respective IDs,
        then generates a PDF document by rendering the DocapiTemplate with the CmdbObject's data.

        Steps involved:
            1. Fetch the template using the template ID (`doctpl_id`)
            2. Retrieve the CMDB object using the object ID (`object_id`)
            3. Fetch the object type information for the CMDB object
            4. Create a `CmdbRender` object to prepare the data
            5. Use `ObjectDocumentGenerator` to generate a PDF document
            6. Return the generated PDF as a BytesIO object

        Returns:
            BytesIO: A file-like object containing the generated PDF document
        """
        cmdb_render_object: RenderResult = CmdbMultiRender(
            [self.target_object],
            request_user
        ).result(single_object=True)

        generator = ObjectDocumentGenerator(
            self.target_template,
            cmdb_render_object,
            PdfDocumentType(),
            self.objects_manager,
            request_user
        )

        return generator.generate_doc()
