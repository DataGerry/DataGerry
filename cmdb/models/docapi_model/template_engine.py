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
Implementation of the TemplateEngine
"""
import logging
from jinja2 import Environment, ChainableUndefined
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                TemplateEngine - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TemplateEngine:
    """
    A class responsible for rendering templates using Jinja2

    This class uses the Jinja2 template engine to render a template string
    with the provided data. It allows for dynamic content generation by
    combining templates with variables.
    """

    def render_template_string(self, template_string, template_data) -> str:
        """
        Renders a template string with the given data using Jinja2.

        This method creates a Jinja2 `Environment` instance, loads the template string,
        and renders it using the provided `template_data`.

        Args:
            template_string (str): The Jinja2 template string to be rendered
            template_data (Dict[str, Any]): A dictionary containing the data to be inserted into the template

        Returns:
            str: The rendered template string with the provided data
        """
        # Initialize the Jinja2 environment with ChainableUndefined to handle undefined variables gracefully
        environment = Environment(undefined=ChainableUndefined)

        # ---- REGISTER FUNCTIONS ----
        environment.globals["object"] = lambda public_id: (
            template_data.get("objects", {}).get(public_id)
        )

        environment.globals["root"] = template_data.get("root")

        # reports
        environment.globals["report"] = lambda public_id: (
            template_data.get("reports", {}).get(public_id)
        )

        # Load the template string into the Jinja2 environment
        template = environment.from_string(template_string)

        return template.render(template_data)
