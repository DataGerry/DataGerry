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

`TemplateEngine` renders a DocAPI document template (an admin-authored HTML string) with object /
report data using Jinja2, producing the HTML that is then converted to PDF. Rendering is made
crash-tolerant so a missing field never aborts a document:

- ``undefined=ChainableUndefined`` lets undefined variables chain without raising;
- the data is wrapped via `safe_wrap` (`SafeDict` / `SafeNull`) so missing keys/attributes resolve
  to a blank `SafeNull`;
- the ``object(id)`` / ``root`` / ``report(id)`` globals fall back to a `SafeObject` when the id is
  unknown;
- `_finalize` renders ``None`` / empty string / `SafeNull` / `SafeObject` as a non-breaking space;
- ``autoescape`` is enabled, so interpolated field values are HTML-escaped (the `SafeNull` /
  `SafeObject` ``__html__`` hooks supply their blank markup) — the template markup itself is
  authored HTML and is not escaped.
"""
from logging import Logger, getLogger
from typing import Any

from jinja2 import Environment, ChainableUndefined

from cmdb.models.docapi_model.safe_null import SafeNull
from cmdb.models.docapi_model.safe_object import SafeObject
from cmdb.models.docapi_model.safe_wrap import safe_wrap
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

NBSP: str = "\u00A0"

# -------------------------------------------------------------------------------------------------------------------- #
#                                                TemplateEngine - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TemplateEngine:
    """
    Renders DocAPI document templates with Jinja2, degrading missing data to blank cells
    """

    @staticmethod
    def _finalize(value: Any) -> Any:
        """
        Jinja2 ``finalize`` hook: renders absent / null values as a non-breaking space

        Args:
            value (Any): The value Jinja2 is about to output

        Returns:
            Any: A non-breaking space for ``None`` / empty string / `SafeNull` / `SafeObject`,
                otherwise the value unchanged
        """
        if value is None or isinstance(value, (SafeNull, SafeObject)):
            return NBSP

        if isinstance(value, str) and value == "":
            return NBSP

        return value


    @staticmethod
    def render_template_string(template_string: str, template_data: dict[str, Any]) -> str:
        """
        Renders a Jinja2 template string with the given data

        Builds a Jinja2 `Environment` (autoescaping, chainable undefined), wraps the data so
        missing lookups stay render-safe, exposes the ``object`` / ``root`` / ``report`` globals
        with `SafeObject` fallbacks, and renders. On any unexpected rendering error the raw
        template string is returned so the resulting document is not empty.

        Args:
            template_string (str): The Jinja2 template string to render
            template_data (dict[str, Any]): The data to insert into the template

        Returns:
            str: The rendered template, or the raw `template_string` if rendering failed
        """
        environment = Environment(autoescape=True, undefined=ChainableUndefined)
        environment.finalize = TemplateEngine._finalize

        safe_template_data = safe_wrap(template_data)
        safe_fallback = SafeObject()

        environment.globals["object"] = lambda public_id: (
            safe_template_data.get("objects", {}).get(public_id, safe_fallback)
        )
        environment.globals["root"] = safe_template_data.get("root", safe_fallback)
        environment.globals["report"] = lambda public_id: (
            safe_template_data.get("reports", {}).get(public_id, safe_fallback)
        )

        template = environment.from_string(template_string)

        try:
            return template.render(safe_template_data)
        except Exception as err:
            LOGGER.error("Template rendering failed (unexpected fatal error): %s", err)
            return template_string  # fallback: return raw template so PDF is not empty
