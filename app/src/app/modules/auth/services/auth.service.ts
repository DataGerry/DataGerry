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
import { HttpBackend, HttpClient, HttpHeaders, HttpParams } from '@angular/common/http';
import { Router } from '@angular/router';

import { BehaviorSubject, Observable } from 'rxjs';
import { map } from 'rxjs/operators';

import { NgbModal, NgbModalOptions } from '@ng-bootstrap/ng-bootstrap';
import { NgxIndexedDBService } from 'ngx-indexed-db';

import { PermissionService } from './permission.service';
import { ConnectionService } from '../../connect/services/connection.service';
import { ApiCallService, ApiServicePrefix, httpObserveOptions } from '../../../services/api-call.service';
import { SpecialService } from '../../../framework/services/special.service';

import { User } from '../../../management/models/user';
import { IntroComponent } from '../../../layout/intro/intro.component';
import { LoginResponse } from '../models/responses';
import { Token } from '../models/token';
import { BranchInfoModalComponent } from 'src/app/layout/intro/branch-info-modal/branch-info-modal.component';
import { ProfileInfoModalComponent } from 'src/app/layout/intro/profile-info-modal/profile-info-modal.component';
import { SubscriptionItem } from '../models/SubscriptionItem';
/* ------------------------------------------------------------------------------------------------------------------ */

const httpOptions = {
    headers: new HttpHeaders({
        'Content-Type': 'application/json'
    })
};


@Injectable({
    providedIn: 'root'
})
export class AuthService<T = any> implements ApiServicePrefix {
    // Rest backend
    private restPrefix: string = 'rest';
    public readonly servicePrefix: string = 'auth';
    private http: HttpClient;

    // User storage
    private currentUserSubject: BehaviorSubject<User>;
    public currentUser: Observable<User>;
    private currentUserTokenSubject: BehaviorSubject<Token>;
    public currentUserToken: Observable<Token>;

    // First Step Intro
    private startIntroModal: any = undefined;
    private stepByStepModal: any = undefined;

    private branchInfoModal: any = undefined;
    private profileInfoModal: any = undefined;

    /* -------------------------------------------------- GETTER/SETTER ------------------------------------------------- */

    public get currentUserValue(): User {
        return this.currentUserSubject.value;
    }

    public get currentUserTokenValue(): Token {
        return this.currentUserTokenSubject.value;
    }

    /* ------------------------------------------------------------------------------------------------------------------ */
    /*                                                     LIFE CYCLE                                                     */
    /* ------------------------------------------------------------------------------------------------------------------ */

    constructor(
        public backend: HttpBackend,
        private connectionService: ConnectionService,
        private api: ApiCallService,
        private permissionService: PermissionService,
        private router: Router,
        private introService: NgbModal,
        private specialService: SpecialService,
        private indexDB: NgxIndexedDBService) {

        this.http = new HttpClient(backend);
        this.currentUserSubject = new BehaviorSubject<User>(JSON.parse(localStorage.getItem('current-user')));
        this.currentUser = this.currentUserSubject.asObservable();

        this.currentUserTokenSubject = new BehaviorSubject<Token>(JSON.parse(localStorage.getItem('access-token')));
        this.currentUserToken = this.currentUserTokenSubject.asObservable();
    }


    public getProviders(): Observable<Array<T>> {
        return this.api.callGet<Array<T>>(`${this.servicePrefix}/providers`, this.getHttpOptions()).pipe(
            map((apiResponse) => {
                return apiResponse.body as Array<T>;
            })
        );
    }


    public getSettings(): Observable<T> {
        return this.api.callGet<T[]>(`${this.servicePrefix}/settings`, this.getHttpOptions()).pipe(
            map((apiResponse) => {
                return apiResponse.body;
            })
        );
    }


    public postSettings(data: T): Observable<T> {
        return this.api.callPost<T>(`${this.servicePrefix}/settings`, data, this.getHttpOptions()).pipe(
            map((apiResponse) => {
                return apiResponse.body;
            })
        );
    }

    /* -------------------------------------------------- LOGIN/LOGOUT -------------------------------------------------- */
    /**
     * Logs in the user with the provided credentials.
     * Stores user and token details on successful login.
     */
    public login(username: string, password: string): Observable<LoginResponse | Array<SubscriptionItem>> {
        const data = {
            user_name: username,
            password
        };

        return this.http
            .post<LoginResponse | Array<SubscriptionItem>>(
                `${this.connectionService.getApiBaseUrl()}/${this.restPrefix}/${this.servicePrefix}/login`,
                data,
                httpOptions
            )
            .pipe(map((response) => {
                if (Array.isArray(response)) {
                    return response;
                } else {
                    const loginResponse = response as LoginResponse;
                    const token: Token = {
                        token: loginResponse.token,
                        issued: loginResponse.token_issued_at,
                        expire: loginResponse.token_expire
                    };

                    localStorage.setItem('current-user', JSON.stringify(loginResponse.user));
                    localStorage.setItem('access-token', JSON.stringify(token));
                    this.currentUserSubject.next(loginResponse.user);
                    this.currentUserTokenSubject.next(token);
                    this.showIntro();

                    return loginResponse;
                }
            }));
    }

    /**
     * Selects a subscription and updates user and token details.
     */
    public selectSubscription(payload: any): Observable<LoginResponse> {
        return this.http
            .post<LoginResponse>(
                `${this.connectionService.getApiBaseUrl()}/${this.restPrefix}/${this.servicePrefix}/login`,
                payload,
                httpOptions
            )
            .pipe(
                map((loginResponse: LoginResponse) => {
                    const token: Token = {
                        token: loginResponse.token,
                        issued: loginResponse.token_issued_at,
                        expire: loginResponse.token_expire
                    };

                    localStorage.setItem('current-user', JSON.stringify(loginResponse.user));
                    localStorage.setItem('access-token', JSON.stringify(token));
                    this.currentUserSubject.next(loginResponse.user);
                    this.currentUserTokenSubject.next(token);

                    return loginResponse;
                })
            );
    }


    public logout() {
        this.indexDB.clear('user-settings').subscribe();
        localStorage.removeItem('current-user');
        localStorage.removeItem('access-token');

        this.currentUserSubject.next(undefined);
        this.currentUserTokenSubject.next(undefined);
        this.permissionService.clearUserRightStorage();

        // Close Intro-Modal if open
        if (this.startIntroModal !== undefined) {
            this.startIntroModal.close();
        }
        if (this.stepByStepModal !== undefined) {
            this.stepByStepModal.close();
        }
        this.router.navigate(['/auth']);
    }

    /* -------------------------------------------------- INTRO SECTION ------------------------------------------------- */

    public showIntro(triggered: boolean = false) {
        this.specialService.getIntroStarter().subscribe(showAssistant => {
            if (showAssistant) {
                this.startIntroModal = this.introService.open(IntroComponent, this.getModalOptions());

                this.startIntroModal.result.then((result) => {
                    if (result) {
                        this.showBranchInfoModal();
                    }
                },
                    (error) => {
                    });
            } else {
                //display assistant not usable
                if (triggered) {
                    this.startIntroModal = this.introService.open(IntroComponent, this.getModalOptions());
                    this.startIntroModal.componentInstance.isUsable = false;
                }
            }
        });
    }


    /**
     * Modal for branch selection
     */
    private showBranchInfoModal(selectedBranches = {}) {
        this.branchInfoModal = this.introService.open(BranchInfoModalComponent, this.getModalOptions());
        this.branchInfoModal.componentInstance.selectedBranches = selectedBranches;
        this.branchInfoModal.componentInstance.setBranchState(selectedBranches);

        this.branchInfoModal.result.then((result: any) => {
            if (result) {
                this.showProfileInfoModal(result);
            }
        },
            (error) => {
            });
    }


    /**
     * Modal for profile selection
     * 
     * @param selectedBranches (dict): selected branches from branch modal
     */
    private showProfileInfoModal(selectedBranches) {
        this.profileInfoModal = this.introService.open(ProfileInfoModalComponent, this.getModalOptions());
        this.profileInfoModal.componentInstance.selectedBranches = selectedBranches;
        this.profileInfoModal.componentInstance.setProfiles(selectedBranches);

        this.profileInfoModal.result.then((result: any) => {
            if (result == 'back') {
                this.showBranchInfoModal(selectedBranches);
            } else {
                let selectedProfiles: string = "";

                //filter selected profiles
                for (let profile of Object.keys(result)) {
                    if (result[profile]) {
                        selectedProfiles += profile + "#";
                    }
                }

                selectedProfiles = selectedProfiles.slice(0, -1);

                this.specialService.createProfiles(selectedProfiles).subscribe({
                    next: () => {
                        this.router.navigate(['/framework/type/']);
                    },
                    error: (error) => {
                        // console.log("createProfiles error occured:", error);
                    }
                });
            }
        },
            (error) => {
            });
    }

    /* ------------------------------------------------- HELPER SECTION ------------------------------------------------- */



    private getHttpOptions() {
        const options = httpObserveOptions;
        options.params = new HttpParams();

        return options
    }


    private getModalOptions(): NgbModalOptions {
        return {
            centered: true,
            backdrop: 'static',
            keyboard: true,
            windowClass: 'intro-tour',
            size: 'lg'
        };
    }

    /* ------------------------------------------------- ENTRA ID SECTION ------------------------------------------------ */

    /**
     * Check if Entra ID authentication is enabled on the backend
     * @returns Observable with enabled status
     */
    public getEntraIdStatus(): Observable<{ enabled: boolean }> {
        return this.http.get<{ enabled: boolean }>(
            `${this.connectionService.getApiBaseUrl()}/${this.restPrefix}/${this.servicePrefix}/entraid/status`
        );
    }


    /**
     * Initiates the Entra ID OAuth2 login flow
     * Redirects the browser to Microsoft's login page
     */
    public initiateEntraIdLogin(): void {
        window.location.href = `${this.connectionService.getApiBaseUrl()}/${this.restPrefix}/${this.servicePrefix}/entraid/login`;
    }


    /**
     * Handle Entra ID callback token from URL parameters
     * Called when returning from Microsoft OAuth flow
     * @param token The JWT token from the callback URL
     * @param expires Token expiration timestamp
     */
    public handleEntraIdCallback(token: string, expires: number): void {
        const tokenObj: Token = {
            token: token,
            issued: Math.floor(Date.now() / 1000),
            expire: expires
        };

        localStorage.setItem('access-token', JSON.stringify(tokenObj));
        this.currentUserTokenSubject.next(tokenObj);

        // Fetch user info using the token
        // The user will be fetched on next authenticated request
    }
}