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
import { ChangeDetectionStrategy, Component, DestroyRef, computed, effect, inject, input, output, signal, untracked } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { FormControl, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { finalize } from 'rxjs';

import { CoreModule } from 'src/app/core/core.module';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { PersonSyncService } from 'src/app/management/services/person-sync.service';
import { GroupSyncSettings, SyncPassCounts } from 'src/app/management/models/person-sync';
/* ------------------------------------------------------------------------------------------------------------------ */

/** The user group sync switch; usable only while the person sync is on. Mappings are made on the Groups page. */
@Component({
    selector: 'app-group-sync-settings',
    standalone: true,
    imports: [CoreModule, ReactiveFormsModule, RouterLink],
    templateUrl: './group-sync-settings.component.html',
    styleUrls: ['./group-sync-settings.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class GroupSyncSettingsComponent {

    private readonly personSyncService = inject(PersonSyncService);
    private readonly loaderService = inject(LoaderService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    /** The stored person sync state, null until it is loaded; switching it off also switches the group sync off. */
    public readonly userSyncActive = input<boolean | null>(null);

    public readonly passCompleted = output<SyncPassCounts>();

    protected readonly settings = signal<GroupSyncSettings | null>(null);
    protected readonly isBusy = signal(false);

    protected readonly mappingCount = computed(() => this.settings()?.mappings?.length ?? 0);

    protected readonly form = new FormGroup({
        active: new FormControl(false, { nonNullable: true })
    });

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    constructor() {
        effect(() => {
            const userSyncActive = this.userSyncActive();

            untracked(() => this.onUserSyncChange(userSyncActive));
        });

        effect(() => this.syncControl());

        this.form.controls.active.valueChanges
            .pipe(takeUntilDestroyed())
            .subscribe(active => this.saveSettings(active));
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    /**
     * Read once when the person sync state is known. Switching the person sync off also switches the group sync off
     * server side, so that is mirrored here instead of read again through the short-lived GET cache.
     */
    private onUserSyncChange(userSyncActive: boolean | null): void {
        const settings = this.settings();

        if (userSyncActive === null) {
            return;
        }

        if (!settings) {
            this.loadSettings();
            return;
        }

        if (!userSyncActive && settings.active) {
            this.settings.set({ ...settings, active: false });
        }
    }


    private loadSettings(): void {
        this.loaderService.show();

        this.personSyncService.getGroupSync()
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                finalize(() => this.loaderService.hide())
            )
            .subscribe({
                next: (settings) => this.settings.set(settings),
                error: (error: HttpErrorResponse) => this.toastService.error(error?.error?.message)
            });
    }


    private saveSettings(active: boolean): void {
        this.isBusy.set(true);
        this.loaderService.show();

        this.personSyncService.updateGroupSync(active)
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                finalize(() => {
                    this.isBusy.set(false);
                    this.loaderService.hide();
                })
            )
            .subscribe({
                next: (pass) => {
                    this.settings.set(pass.result);
                    this.passCompleted.emit(pass);
                    this.toastService.success(`The group sync was switched ${ active ? 'on' : 'off' }!`);
                },
                error: (error: HttpErrorResponse) => this.toastService.error(error?.error?.message)
            });
    }


    /** Mirrors the stored switch without re-sending it; a refused write falls back to the stored state. */
    private syncControl(): void {
        const control = this.form.controls.active;
        const isBusy = this.isBusy();

        if (!isBusy) {
            control.setValue(this.settings()?.active === true, { emitEvent: false });
        }

        if (this.userSyncActive() === true && !isBusy && this.settings()) {
            control.enable({ emitEvent: false });
        } else {
            control.disable({ emitEvent: false });
        }
    }
}
