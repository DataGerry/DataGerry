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
Naming of exported files (framework layer)

Both export paths - the object export engine (`BaseExportWriter.export`) and the CmdbType export
(`exporter_helper.build_types_json_export_response`) - stamp their download filename with the same
timestamp. Keeping that in one place is what makes the timezone a single decision rather than two
independent ones
"""
from datetime import datetime, timezone

from cmdb.framework.exporter.exporter_constants import EXPORT_FILENAME_TIMESTAMP_FMT
# -------------------------------------------------------------------------------------------------------------------- #

def build_export_filename_timestamp() -> str:
    """
    Builds the timestamp that names an exported file

    The stamp is taken in UTC rather than the server's local timezone, so exports of the same system
    sort and compare consistently no matter where the instance runs. Note the format carries no
    timezone marker, so the value is only meaningful as an identifier, not as a displayed local time

    Returns:
        str: The current UTC time formatted per EXPORT_FILENAME_TIMESTAMP_FMT, e.g. `2026_07_27-13_05_00`
    """
    return datetime.now(timezone.utc).strftime(EXPORT_FILENAME_TIMESTAMP_FMT)
