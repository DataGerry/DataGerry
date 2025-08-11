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
Blueprint for handling routes in the datagerry-app.
This module defines a Flask Blueprint for serving static files and handling 404 errors
"""
import logging
from flask import Blueprint, Response
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

app_pages = Blueprint("app_pages", __name__, static_folder="datagerry-app", static_url_path="")

# -------------------------------------------------------------------------------------------------------------------- #
@app_pages.route('/')
def default_page() -> Response:
    """
    Serves the default static index page
    
    Returns:
        Response: The static index.html file
    """
    return app_pages.send_static_file("index.html")


#pylint: disable=W0613
@app_pages.errorhandler(404)
def redirect_index(error) -> Response:
    """
    Handles 404 errors by redirecting to the index page
    
    Args:
        error (Exception): The exception object representing the 404 error
    
    Returns:
        Response: The static index.html file
    """
    return app_pages.send_static_file("index.html")
