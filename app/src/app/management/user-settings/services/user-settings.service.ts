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
import { HttpHeaders, HttpParams, HttpResponse } from '@angular/common/http';

import { Observable, map } from 'rxjs';

import { ApiCallService, ApiServicePrefix, resp } from '../../../services/api-call.service';
import { AuthService } from '../../../modules/auth/services/auth.service';

import { UserSetting, UserSettingPayload } from '../models/user-setting';
import { User } from '../../models/user';
import {
    APIDeleteSingleResponse,
    APIGetListResponse, APIGetSingleResponse,
    APIInsertSingleResponse,
    APIUpdateSingleResponse
} from '../../../services/models/api-response';
/* ------------------------------------------------------------------------------------------------------------------ */

    export function convertResourceURL(url: string): string {
        return url.substring(1).split('/').join('-');
    }


/**
 * Service class for API user settings.
 */
@Injectable({
    providedIn: 'root'
})
export class UserSettingsService<T = UserSetting, P = UserSettingPayload> implements ApiServicePrefix {

    // Default REST URL Prefix
    public servicePrefix: string;

    public currentUser: User;
    public currentUserObservable: Observable<User>;


    public readonly options = {
        headers: new HttpHeaders({
        'Content-Type': 'application/json'
        }),
        params: {},
        observe: resp
    };


    /**
     * Constructor of `UserSettingsService`.
     * Generates the servicePrefix as `users/{USER_ID}/settings`.
     *
     * @param api: ApiCallService
     * @param authService: AuthService
     */
    constructor(private api: ApiCallService, private authService: AuthService) {
        this.currentUserObservable = this.authService.currentUser;
        this.currentUserObservable.subscribe((user: User) => {
            this.currentUser = user;
            this.servicePrefix = `users/${ this.authService.currentUserValue?.public_id }/settings`;
        });
    }


    /**
     * Create a user setting.
     * @param resource
     * @param payloads
     */
    public createUserSetting<PAYLOAD>(resource: string, payloads: Array<PAYLOAD>): UserSetting<PAYLOAD> {
        return new UserSetting<PAYLOAD>(resource, this.currentUser.public_id, payloads);
    }


    /**
     * Get all settings from the logged user.
     */
    public getUserSettings(): Observable<Array<T>> {
        const options = this.options;
        options.params = new HttpParams();

        return this.api.callGet<T>(`users/${ this.authService.currentUserValue?.public_id }/settings/`, options).pipe(
            map((apiResponse: HttpResponse<APIGetListResponse<T>>) => {
                return apiResponse.body.results as Array<T>;
            })
        );
    }


    /**
     * Get a specific setting from the logged user.
     * @param identifier of the setting.
     */
    public getUserSetting(identifier: string): Observable<T> {
        const options = this.options;
        options.params = new HttpParams();
    
        return this.api.callGet<T>(`users/${ this.authService.currentUserValue.public_id }/settings/${ identifier }/`, options).pipe(
            map((apiResponse: HttpResponse<APIGetSingleResponse<T>>) => {
                return apiResponse.body.result as T;
            })
        );
    }


    /**
     * Add a new setting for the logged in user.
     * @param setting data.
     */
    public addUserSetting(setting: T): Observable<T> {
        const options = this.options;
        options.params = new HttpParams();

        return this.api.callPost<T>(`users/${ this.authService.currentUserValue.public_id }/settings/`, setting, options).pipe(
            map((apiResponse: HttpResponse<APIInsertSingleResponse<T>>) => {
                return apiResponse.body.raw as T;
            })
        );
    }


    /**
     * Update a existing user setting by its identifier.
     * @param identifier of the setting.
     * @param setting data.
     */
    public updateUserSetting(identifier: string, setting: T): Observable<T> {
        const options = this.options;
        options.params = new HttpParams();
    
        return this.api.callPut<T>(`users/${ this.authService.currentUserValue.public_id }/settings/${ identifier }`, setting, options).pipe(
            map((apiResponse: HttpResponse<APIUpdateSingleResponse<T>>) => {
                return apiResponse.body.result as T;
            })
        );
    }


    /**
     * Delete a specific user setting by its identifier.
     * @param identifier of the setting.
     */
    public deleteUserSetting(identifier: string): Observable<T> {
        const options = this.options;
        options.params = new HttpParams();

        return this.api.callDelete<T>(`users/${ this.authService.currentUserValue.public_id }/settings/${ identifier }`, options).pipe(
            map((apiResponse: HttpResponse<APIDeleteSingleResponse<T>>) => {
                return apiResponse.body.raw as T;
            })
        );
    }
}