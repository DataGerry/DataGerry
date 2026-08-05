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
Implementation of Priority enumeration
"""
from enum import Enum
# -------------------------------------------------------------------------------------------------------------------- #

class Priority(int, Enum):
    """
    Available Priority for IsmsRiskAssessments
    """
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    VERY_HIGH = 4


    @classmethod
    def is_valid(cls, value: int) -> bool:
        """
        Checks if a given value is a valid Priority

        Args:
            value (int): The value to check

        Returns:
            bool: True if the value matches an existing Priority, False otherwise
        """
        return value in cls._value2member_map_
