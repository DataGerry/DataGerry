# DataGerry - OpenSource Enterprise CMDB
# Copyright (C) 2025 becon GmbH
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
Blueprint for documentation routes
"""
from cmdb.interface.blueprints import RootBlueprint
# -------------------------------------------------------------------------------------------------------------------- #

doc_pages = RootBlueprint("doc_pages", __name__, static_folder="static", static_url_path="")

# -------------------------------------------------------------------------------------------------------------------- #

@doc_pages.route("/")
def default_page():
    """
    Handles the request for the default page (index page) of the documentation

    This function is mapped to the root URL (`/`) of the documentation pages. When a request 
    is made to this URL, it serves the `index.html` file as the response. This is typically 
    the main landing page for the documentation interface

    Returns:
        Response: The response object containing the `index.html` file
    """
    return doc_pages.send_static_file("index.html")
