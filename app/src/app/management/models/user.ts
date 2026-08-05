/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2026 becon GmbH
*
* This program is free software: you can redistribute it and/or modify
* it under the terms of the GNU Affero General Public License as
* published by the Free Software Foundation, either version 3 of the
* License, or (at your option) any later version.
*
* This program is distributed in the hope that it will be useful,
* but WITHOUT ANY WARRANTY; without even the implied warranty of
* MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
* GNU Affero General Public License for more details.

* You should have received a copy of the GNU Affero General Public License
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/

export class User {
  readonly public_id: number;
  public user_name: string;
  public first_name?: string;
  public last_name?: string;
  public email: string;
  public image?: string;
  public password?: string;
  public token?: string;
  public token_expire?: number;
  public token_issued_at?: number;
  public registration_time: string;
  public authenticator: string;
  public group_id: number;
  config_items_limit: number;
}
