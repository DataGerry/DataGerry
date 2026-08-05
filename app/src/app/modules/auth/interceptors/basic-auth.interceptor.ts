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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import { Injectable } from '@angular/core';
import { HttpRequest, HttpHandler, HttpEvent, HttpInterceptor } from '@angular/common/http';

import { BehaviorSubject, Observable } from 'rxjs';

import { User } from '../../../management/models/user';
import { Token } from '../models/token';
/* ------------------------------------------------------------------------------------------------------------------ */
@Injectable()
export class BasicAuthInterceptor implements HttpInterceptor {

  public intercept(request: HttpRequest<any>, next: HttpHandler): Observable<HttpEvent<any>> {
        const currentUser = new BehaviorSubject<User>(JSON.parse(localStorage.getItem('current-user'))).value;
        const currentUserToken = new BehaviorSubject<Token>(JSON.parse(localStorage.getItem('access-token'))).value;
        if (currentUser && currentUserToken) {
            request = request.clone({
                setHeaders: {
                    Authorization: `Bearer ${ currentUserToken.token }`,
                    'Cache-Control': 'no-cache',
                    Pragma: 'no-cache'
                }
            });
        }

        return next.handle(request);
  }
}
