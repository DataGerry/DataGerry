/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2025 becon GmbH
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
import { HttpRequest, HttpHandler, HttpEvent, HttpInterceptor, HttpErrorResponse } from '@angular/common/http';
import { Router } from '@angular/router';

import { Observable, throwError, catchError } from 'rxjs';

import { AuthService } from '../../auth/services/auth.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { environment } from 'src/environments/environment';
/* ------------------------------------------------------------------------------------------------------------------ */

@Injectable()
export class HttpErrorInterceptor implements HttpInterceptor {
    public readonly CONNECTION_REFUSED: number = 0;
    public readonly BAD_REQUEST: number = 400;
    public readonly UNAUTHORIZED: number = 401;
    public readonly FORBIDDEN: number = 403;
    public readonly NOT_FOUND: number = 404;
    public readonly METHOD_NOT_ALLOWED: number = 405;
    public readonly NOT_ACCEPTABLE: number = 406;
    public readonly PAGE_GONE: number = 410;
    public readonly INTERNAL_SERVER_ERROR: number = 500;

    private readonly REDIRECT_ERRORS: number[] = [
        this.CONNECTION_REFUSED,
        this.UNAUTHORIZED,
        this.INTERNAL_SERVER_ERROR
    ];

/* ------------------------------------------------------------------------------------------------------------------ */
/*                                                     LIFE CYLCLE                                                    */
/* ------------------------------------------------------------------------------------------------------------------ */

    constructor(
        private router: Router, 
        private authService: AuthService,
        private toastService: ToastService,
    ) {

    }


    public intercept(request: HttpRequest<any>, next: HttpHandler): Observable<HttpEvent<any>> {
        return next.handle(request).pipe(catchError((error: HttpErrorResponse) => {
            const statusCode = error.status;

            if (this.REDIRECT_ERRORS.indexOf(statusCode) !== -1) {
                // if (statusCode === this.CONNECTION_REFUSED || statusCode === this.INTERNAL_SERVER_ERROR) {
                //     this.router.navigate(['/connect']);
                // } else if (statusCode === this.UNAUTHORIZED) {
                //     this.authService.logout();
                // } else {
                //     this.router.navigate(['/error/', statusCode]);
                // }
                if (statusCode === this.CONNECTION_REFUSED) {
                    if(!environment.cloudMode){
                        this.router.navigate(['/connect']);
                    }
                    this.toastService.error("The connection to the backend has been refused!");
                }
                // else if (statusCode === this.INTERNAL_SERVER_ERROR) {
                //     // if(!environment.cloudMode){
                //     //     this.router.navigate(['/connect']);
                //     // }
                //     this.toastService.error("An internal server error occured!"); 
                // }
                else if (statusCode === this.UNAUTHORIZED) {
                    this.authService.logout();
                } else {
                    this.router.navigate(['/error/', statusCode]);
                }
            }

            return throwError(() => error);
        }));
    }
}