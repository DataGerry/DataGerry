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
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { Component, OnDestroy, OnInit, Renderer2 } from '@angular/core';
import { Router } from '@angular/router';
import { UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';

import { Subscription, finalize, first } from 'rxjs';

import { AuthService } from '../services/auth.service';
import { PermissionService } from '../services/permission.service';
import { UserSettingsDBService } from '../../../management/user-settings/services/user-settings-db.service';

import { LoginResponse } from '../models/responses';
import { Group } from 'src/app/management/models/group';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { environment } from 'src/environments/environment';
import { strictEmailValidator } from './strictEmailValidator';

@Component({
    selector: 'cmdb-login',
    templateUrl: './login.component.html',
    styleUrls: ['./login.component.scss'],
    standalone: false
})
export class LoginComponent implements OnInit, OnDestroy {
    public static defaultLogoUrl: string = '/assets/img/datagerry_logo.svg';
    public static xmasLogoUrl: string = '/assets/img/datagerry_logo_xmas.svg';
    public static defaultFallItems: string = '/assets/img/nut.svg';
    public static xmasFallItems: string = '/assets/img/snowflake.svg';
    public passwordVisible: boolean = false;


    public imageUrl: string = LoginComponent.defaultLogoUrl;
    public itemUrl: string = LoginComponent.defaultFallItems;

    public loginForm: UntypedFormGroup;
    public submitted = false;

    public subscriptions: Array<any> = [];
    public showSubscriptions = false;
    public isLoading = false;

    private loginSubscription: Subscription = new Subscription();

    public userName: string;
    public userPW: string;

    public isLoading$ = this.loaderService?.isLoading$;

    public  isCloudMode = environment.cloudMode;

    /* -------------------------------------------------- GETTER/SETTER ------------------------------------------------- */
    get controls() {
        return this.loginForm?.controls;
    }

    /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    constructor(
        private router: Router,
        private userSettingsDB: UserSettingsDBService,
        private authenticationService: AuthService,
        private permissionService: PermissionService,
        private render: Renderer2,
        private toastService: ToastService,
        private loaderService: LoaderService
    ) {
        const currentDate = new Date();
        const year = currentDate?.getFullYear();
        const dateBefore = new Date(`${year}-12-18`);
        const dateAfter = new Date(`${year}-12-31`);

        if ((dateBefore < currentDate) && (currentDate < dateAfter)) {
            this.imageUrl = LoginComponent.xmasLogoUrl;
            this.itemUrl = LoginComponent.xmasFallItems;
        }
    }

    public ngOnInit(): void {
        this.render?.addClass(document?.body, 'embedded');
        // const isCloudMode = environment.cloudMode;


        this.loginForm = new UntypedFormGroup({
            username: new UntypedFormControl(
                '',
                this.isCloudMode
                    ? [Validators.required, strictEmailValidator]
                    : [Validators.required]
            ),
            password: new UntypedFormControl('', [Validators.required]),
            subscription: new UntypedFormControl(null)
        });
    }

    public ngOnDestroy(): void {
        this.render?.removeClass(document?.body, 'embedded');
        this.loginSubscription?.unsubscribe();
    }

    /* ------------------------------------------------ HELPER FUNCTIONS ------------------------------------------------ */

    /**
     * First step: user enters credentials (username + password). 
     * If the backend returns an array, show subscription dropdown.
     * Otherwise, it's a normal login.
     */
    public onSubmit() {
        this.submitted = true;
        this.loaderService?.show();

        this.userName = this.loginForm?.controls['username']?.value;
        this.userPW = this.loginForm?.controls['password']?.value;

        this.loginSubscription = this.authenticationService
            .login(this.userName, this.userPW)
            .pipe(first(), finalize(() => this.loaderService?.hide()))
            .subscribe({
                next: (response: LoginResponse | Array<any>) => {

                    // Login with multiple subscriptions
                    if (Array.isArray(response)) {
                        this.isLoading = true;
                        this.subscriptions = response;
                        setTimeout(() => {
                            this.isLoading = false;
                            this.showSubscriptions = true;
                            this.loginForm?.get('subscription')?.reset(null);
                        }, 1000);
                    } else {
                        // Normal login response
                        const loginResponse = response as LoginResponse;

                        this.userSettingsDB?.syncSettings();
                        this.permissionService?.storeUserRights(loginResponse?.user.group_id)
                            .pipe(first())
                            .subscribe((group: Group) => {
                                this.router?.navigate(['/']);
                            });
                    }
                },
                error: (err) => {
                    const isNullPath = err.url?.includes('/null/rest');
                    if (!environment.cloudMode && err?.status === 404 || err?.status === 0) {
                        this.router?.navigate(['/connect']);
                        this.isLoading = false;
                    } else if (environment.cloudMode && isNullPath) {
                        localStorage?.removeItem('connection');
                    }

                    this.isLoading = false;
                    this.toastService?.error(err?.error?.message)
                    this.render?.addClass(document?.getElementById('login-logo'), 'shake');
                    setTimeout(() => {
                        this.render?.removeClass(document?.getElementById('login-logo'), 'shake');
                    }, 500);
                }
            });
    }


    /**
     * Second step: user chooses one subscription from the dropdown and clicks "Proceed".
     * We send only the subscription object to the backend, then get the final token + user, store them, etc.
     */
    public onSelectSubscription(): void {

        const chosenSub = this.loginForm?.get('subscription')?.value;
        if (!chosenSub) {
            return;
        }

        this.loaderService?.show();

        const payload = {
            user_name: this.userName,
            password: this.userPW,
            subscription: chosenSub
        };

        this.loginSubscription = this.authenticationService
            .selectSubscription(payload)
            .pipe(first(), finalize(() => this.loaderService?.hide()))
            .subscribe({
                next: (loginResponse: LoginResponse) => {
                    this.userSettingsDB?.syncSettings();
                    this.permissionService
                        .storeUserRights(loginResponse?.user.group_id)
                        .pipe(first())
                        .subscribe(() => {
                            this.router?.navigate(['/']);
                            this.authenticationService.showIntro();
                        });
                },
                error: (err) => {
                    this.toastService?.error(err?.error?.message)
                },
            });
    }


    /**
     * Triggers form submission when the Enter key is pressed and the form is valid.
     * @param event - The keyboard event.
     */
    public onKeydown(event: KeyboardEvent): void {
        if (event?.key === 'Enter' && this.loginForm?.valid) {
            event?.preventDefault();
            this.onSubmit();
        }
    }


    /**
     * Returns the placeholder text for the login input field.
     * @returns 'Email' if in cloud mode, otherwise 'Username'.
     */
    get userIdentifierPlaceholder(): string {
        return environment?.cloudMode ? 'Email' : 'Username';
    }


    /**
     * Go back to login fields
     */
    public goBack(): void {
        this.showSubscriptions = false;
        this.loginForm?.get('subscription')?.reset(null);
    }


    /**
     * Toggles the visibility of the password input field.
     */
    public togglePasswordVisibility(): void {
        this.passwordVisible = !this.passwordVisible;
    }
}