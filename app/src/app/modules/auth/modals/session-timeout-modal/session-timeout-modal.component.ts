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
import { Component, Input, OnDestroy, OnInit } from '@angular/core';
import { UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';

import { Observable, ReplaySubject, takeUntil } from 'rxjs';

import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';

import { AuthService } from '../../services/auth.service';
import { environment } from 'src/environments/environment';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-session-timeout-modal',
    templateUrl: './session-timeout-modal.component.html',
    styleUrls: ['./session-timeout-modal.component.scss']
})
export class SessionTimeoutModalComponent implements OnInit, OnDestroy {

    private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

    // Timeout observer of the session timeout service
    @Input() public remainingTime$: Observable<string>;


    // Dateformat of the remaining token lifetime
    public remainingTime: string = '';

    // Renew session password form group
    public form: UntypedFormGroup;

    public error: string;

    private isCloudMode: boolean;

    /* -------------------------------------------------- GETTER/SETTER ------------------------------------------------- */

    /**
     * Entered password from the form
     */
    public get password(): string {
        return this.form.get('password').value;
    }

    /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    constructor(public activeModal: NgbActiveModal, private authService: AuthService) {
        this.form = new UntypedFormGroup({
            password: new UntypedFormControl('', Validators.required)
        });
    }


    public ngOnInit(): void {
        this.isCloudMode = environment.cloudMode;
        this.remainingTime$.pipe(takeUntil(this.subscriber)).subscribe((timeout: string) => this.remainingTime = timeout);
    }


    public ngOnDestroy(): void {
        this.subscriber?.next();
        this.subscriber?.complete();
    }

    /* ------------------------------------------------- HELPER METHODS ------------------------------------------------- */

    /**
     * On password pass
     */
    public onRenew(): void {
        if (this.form.valid) {
            const username = this.isCloudMode ? this.authService.currentUserValue.email : this.authService.currentUserValue.user_name

            this.authService.login(username, this.password).pipe(takeUntil(this.subscriber))
                .subscribe({
                    next: () => {
                        this.activeModal.close({ renewed: true });
                    },
                    error: () => {
                        this.error = 'Could not authenticate, given password was wrong.';
                    }
                });
        }
    }
}