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

import { Injectable } from '@angular/core';
import { HttpEvent, HttpRequest, HttpResponse, HttpInterceptor, HttpHandler } from '@angular/common/http';
import { Observable, of } from 'rxjs';
import { tap } from 'rxjs/operators';
import { RequestCacheService } from './request-cache.service';

/**
 * HTTP interceptor which quick caches previous api calls.
 */
@Injectable()
export class APICachingInterceptor implements HttpInterceptor {
  constructor(private cache: RequestCacheService) {
  }

  /**
   * Intercepts the http client.
   * Only assigned to cacheable calls `HEAD` and `GET`
   *
   * @param req the HttpRequest
   * @param next the HttpHandler
   */
  intercept(req: HttpRequest<any>, next: HttpHandler) {
    if (!isCacheable(req)) {
      return next.handle(req);
    }
    const cachedResponse = this.cache.get(req);
    return cachedResponse ? of(cachedResponse) : this.sendRequest(req, next, this.cache);
  }

  /**
   * Save the request into the cache and resend it to the intercepted http call.
   * @param req the HttpRequest
   * @param next the HttpHandler
   * @param cache the RequestCacheService
   */
  sendRequest(
    req: HttpRequest<any>,
    next: HttpHandler,
    cache: RequestCacheService): Observable<HttpEvent<any>> {
    return next.handle(req).pipe(
      tap(event => {
        if (event instanceof HttpResponse) {
          cache.put(req, event);
        }
      })
    );
  }
}

/** Is this request cacheable? */
function isCacheable(req: HttpRequest<any>) {
  return req.method === 'GET' || req.method === 'HEAD';
}

