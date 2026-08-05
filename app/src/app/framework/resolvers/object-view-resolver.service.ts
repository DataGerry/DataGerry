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
*
* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { Injectable } from '@angular/core';
import { ActivatedRouteSnapshot, RouterStateSnapshot } from '@angular/router';

import { Observable } from 'rxjs';

import { ObjectService } from '../services/object.service';

import { RenderResult } from '../models/cmdb-render';
/* ------------------------------------------------------------------------------------------------------------------ */

// Service class for resolving a PublicID to a `RenderResult`.
@Injectable({
  providedIn: 'root'
})
export class ObjectViewResolver  {

  constructor(public objectService: ObjectService) {
  }

  /**
   * Resolves the passed PublicID to a `RenderResult` {@link RenderResult}.
   */
  public resolve(route: ActivatedRouteSnapshot, state: RouterStateSnapshot):
    Observable<RenderResult> | Promise<RenderResult> | RenderResult {
        const publicID: number = +route.paramMap.get('publicID');
        return this.objectService.getObject(publicID);
  }
}