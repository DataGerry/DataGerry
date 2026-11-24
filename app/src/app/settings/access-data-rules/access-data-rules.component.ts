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
import { AsyncPipe } from '@angular/common';
import { RouterLink } from '@angular/router';
import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormArray, FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { EMPTY, Observable, catchError, finalize, forkJoin, map, of, switchMap } from 'rxjs';

import { CoreModule } from 'src/app/core/core.module';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { PermissionService } from 'src/app/modules/auth/services/permission.service';
import { TypeService } from 'src/app/framework/services/type.service';
import { CmdbType } from 'src/app/framework/models/cmdb-type';
import { SpecialType } from 'src/app/framework/models/special-type';
import { UserService } from 'src/app/management/services/user.service';
import { PersonSyncService } from 'src/app/management/services/person-sync.service';
import { User } from 'src/app/management/models/user';
import {
    BlockedPersonRow,
    PersonTypeOverride,
    SyncPassCounts,
    SyncSelectOption,
    UserSyncCheck,
    UserSyncPassResult,
    UserSyncRequest,
    UserSyncSettings
} from 'src/app/management/models/person-sync';
import { PersonSyncDialogService } from 'src/app/management/person-sync/person-sync-dialog.service';
import { SyncPassSummaryComponent } from 'src/app/management/person-sync/components/sync-pass-summary.component';
import { GroupSyncSettingsComponent } from './components/group-sync-settings/group-sync-settings.component';
import { PersonTypeOverrideForm } from './models/access-data-rules.model';
/* ------------------------------------------------------------------------------------------------------------------ */

const INTERNAL_SERVER_ERROR = 500;

const RETRY_MESSAGE = 'The sync pass failed midway. Running it again finishes it.';

const TYPE_ADD_RIGHT = 'base.framework.type.add';


/** Settings > Access & Data Rules: the user -> person sync and the user group sync. */
@Component({
    selector: 'app-access-data-rules',
    standalone: true,
    imports: [AsyncPipe, CoreModule, ReactiveFormsModule, RouterLink, SyncPassSummaryComponent, GroupSyncSettingsComponent],
    templateUrl: './access-data-rules.component.html',
    styleUrls: ['./access-data-rules.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class AccessDataRulesComponent implements OnInit {

    private readonly personSyncService = inject(PersonSyncService);
    private readonly typeService = inject(TypeService);
    private readonly userService = inject(UserService);
    private readonly dialogs = inject(PersonSyncDialogService);
    private readonly loaderService = inject(LoaderService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);
    private readonly permissionService = inject(PermissionService);

    public readonly isLoading$ = this.loaderService.isLoading$;

    public readonly form = new FormGroup({
        active: new FormControl(false, { nonNullable: true }),
        default_type_id: new FormControl<number | null>(null),
        type_overrides: new FormArray<PersonTypeOverrideForm>([])
    });

    /** The settings as the backend holds them; the form is compared against these. */
    public readonly stored = signal<UserSyncSettings | null>(null);
    public readonly typeOptions = signal<SyncSelectOption[]>([]);
    public readonly userOptions = signal<SyncSelectOption[]>([]);
    public readonly lastPass = signal<SyncPassCounts | null>(null);
    public readonly dryRunRows = signal<BlockedPersonRow[] | null>(null);
    public readonly isSaving = signal(false);

    /** Set after a pass failed midway (500); running the same call again finishes it. */
    public readonly retryAction = signal<(() => void) | null>(null);
    public readonly retryMessage = RETRY_MESSAGE;

    public readonly isStoredActive = computed(() => this.stored()?.active === true);

    /** Set once the Types are read, so the notice below never flashes before they arrive. */
    public readonly typesLoaded = signal(false);
    public readonly hasPersonTypes = computed(() => this.typeOptions().length > 0);
    public readonly canAddType = this.permissionService.hasRight(TYPE_ADD_RIGHT)
        || this.permissionService.hasExtendedRight(TYPE_ADD_RIGHT);

    private readonly userLabels = computed(() =>
        new Map(this.userOptions().map(option => [option.public_id, option.label]))
    );

    public get overrides(): FormArray<PersonTypeOverrideForm> {
        return this.form.controls.type_overrides;
    }

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnInit(): void {
        this.loadPage();
    }

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public onAddOverride(): void {
        this.overrides.push(this.createOverride());
        this.form.markAsDirty();
    }


    public onRemoveOverride(index: number): void {
        this.overrides.removeAt(index);
        this.form.markAsDirty();
    }


    public onSave(): void {
        this.form.markAllAsTouched();

        if (this.form.invalid || this.isSaving()) {
            return;
        }

        const request = this.buildRequest();

        this.confirmSwitchOff(request)
            .pipe(
                switchMap(() => this.resolveRelocations(request)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe(resolved => this.saveUserSync(resolved));
    }


    /** Lists the persons the form's settings would move to another Type, and what blocks them. Writes nothing. */
    public onDryRun(): void {
        this.form.markAllAsTouched();

        if (this.form.invalid || this.isSaving()) {
            return;
        }

        this.loaderService.show();

        this.personSyncService.checkUserSync(this.buildRequest())
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                finalize(() => this.loaderService.hide())
            )
            .subscribe({
                next: (check) => this.dryRunRows.set(this.toRows(check)),
                error: (error: HttpErrorResponse) => this.toastService.error(error?.error?.message)
            });
    }


    public onRunSync(): void {
        if (this.isSaving()) {
            return;
        }

        this.runPass(this.personSyncService.resync(), () => this.onRunSync(), false);
    }


    public onRetry(): void {
        this.retryAction()?.();
    }


    public onGroupPass(pass: SyncPassCounts): void {
        this.lastPass.set(pass);
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private loadPage(): void {
        this.loaderService.show();

        forkJoin({
            settings: this.personSyncService.getUserSync(),
            types: this.typeService.getTypes({
                filter: { special_type: SpecialType.PERSON },
                limit: 0,
                sort: 'label',
                order: 1,
                page: 1
            }),
            users: this.userService.getUsers({ filter: undefined, limit: 0, sort: 'user_name', order: 1, page: 1 })
        })
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                finalize(() => this.loaderService.hide())
            )
            .subscribe({
                next: ({ settings, types, users }) => {
                    this.typeOptions.set((types?.results ?? []).map(type => this.toTypeOption(type)));
                    this.userOptions.set((users?.results ?? []).map(user => this.toUserOption(user)));
                    this.typesLoaded.set(true);
                    this.applySettings(settings);
                },
                error: (error: HttpErrorResponse) => this.toastService.error(error?.error?.message)
            });
    }


    private confirmSwitchOff(request: UserSyncRequest): Observable<void> {
        if (!this.isStoredActive() || request.active) {
            return of(undefined);
        }

        return this.dialogs.confirm({
            title: 'Switch off the person sync',
            message: 'Do you want to switch off the person sync?',
            warningMessage: 'Every synced person is deactivated, and the group sync is switched off too.',
            confirmLabel: 'Switch off',
            confirmTone: 'danger'
        });
    }


    /** A changed target Type is checked first, so persons that would move are confirmed before anything is written. */
    private resolveRelocations(request: UserSyncRequest): Observable<UserSyncRequest> {
        if (!this.targetsChanged(request)) {
            return of(request);
        }

        this.loaderService.show();

        return this.personSyncService.checkUserSync(request).pipe(
            finalize(() => this.loaderService.hide()),
            catchError((error: HttpErrorResponse) => {
                this.toastService.error(error?.error?.message);

                return EMPTY;
            }),
            switchMap(check => this.confirmRelocations(check, request))
        );
    }


    private confirmRelocations(check: UserSyncCheck, request: UserSyncRequest): Observable<UserSyncRequest> {
        const rows = this.toRows(check);

        if (!rows.length) {
            return of(request);
        }

        if (!check.blocked) {
            return this.dialogs.confirm({
                title: 'Move persons',
                message: `${ rows.length } person(s) move to their new Type.`,
                confirmLabel: 'Move'
            }).pipe(map(() => request));
        }

        return this.dialogs.confirmCopyBlocked(rows).pipe(map(() => ({ ...request, on_blocked: 'copy' as const })));
    }


    private saveUserSync(request: UserSyncRequest): void {
        this.runPass(this.personSyncService.updateUserSync(request), () => this.saveUserSync(request));
    }


    /** A settings save answers the stored settings; a resync answers only its counts. */
    private runPass(
        pass$: Observable<UserSyncPassResult | SyncPassCounts>,
        retry: () => void,
        answersSettings = true
    ): void {
        this.isSaving.set(true);
        this.retryAction.set(null);
        this.loaderService.show();

        pass$
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                finalize(() => {
                    this.isSaving.set(false);
                    this.loaderService.hide();
                })
            )
            .subscribe({
                next: (pass) => {
                    this.lastPass.set(pass);
                    this.dryRunRows.set(null);

                    if (answersSettings) {
                        this.applySettings((pass as UserSyncPassResult).result);
                    }

                    this.toastService.success('The person sync was updated!');
                },
                error: (error: HttpErrorResponse) => {
                    if (error?.status === INTERNAL_SERVER_ERROR) {
                        this.retryAction.set(retry);
                        return;
                    }

                    this.toastService.error(error?.error?.message);
                }
            });
    }


    private applySettings(settings: UserSyncSettings): void {
        this.stored.set(settings);
        this.overrides.clear();

        for (const override of settings?.type_overrides ?? []) {
            this.overrides.push(this.createOverride(override));
        }

        this.form.patchValue({
            active: settings?.active ?? false,
            default_type_id: settings?.default_type_id ?? null
        });
        this.lockSwitchWithoutPersonType();
        this.form.markAsPristine();
    }


    /** Without a PERSON Type there is nothing to sync into; a sync that is already on can still be switched off. */
    private lockSwitchWithoutPersonType(): void {
        const control = this.form.controls.active;

        if (this.typesLoaded() && !this.hasPersonTypes() && !control.value) {
            control.disable({ emitEvent: false });
        } else {
            control.enable({ emitEvent: false });
        }
    }


    private buildRequest(): UserSyncRequest {
        const value = this.form.getRawValue();

        return {
            active: value.active,
            default_type_id: value.default_type_id ?? null,
            type_overrides: value.type_overrides.map(override => ({
                user_id: override.user_id,
                type_id: override.type_id
            }))
        };
    }


    private targetsChanged(request: UserSyncRequest): boolean {
        const stored = this.stored();

        if (!stored) {
            return false;
        }

        return stored.default_type_id !== request.default_type_id
            || this.overrideKey(stored.type_overrides) !== this.overrideKey(request.type_overrides);
    }


    private overrideKey(overrides: PersonTypeOverride[]): string {
        return (overrides ?? [])
            .map(override => `${ override.user_id }:${ override.type_id }`)
            .sort()
            .join(',');
    }


    private toRows(check: UserSyncCheck): BlockedPersonRow[] {
        return (check?.relocations ?? []).map(relocation => ({
            ...relocation,
            user_label: this.userLabels().get(relocation.user_id) ?? `#${ relocation.user_id }`
        }));
    }


    private createOverride(override?: PersonTypeOverride): PersonTypeOverrideForm {
        return new FormGroup({
            user_id: new FormControl<number | null>(override?.user_id ?? null, Validators.required),
            type_id: new FormControl<number | null>(override?.type_id ?? null, Validators.required)
        });
    }


    private toTypeOption(type: CmdbType): SyncSelectOption {
        const label = type.label || type.name;

        return { public_id: type.public_id, label: type.active ? label : `${ label } (deactivated)` };
    }


    private toUserOption(user: User): SyncSelectOption {
        return { public_id: user.public_id, label: user.user_name };
    }
}
