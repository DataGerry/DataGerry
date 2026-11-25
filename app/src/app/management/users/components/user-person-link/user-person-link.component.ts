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
import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, inject, input, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { RouterLink } from '@angular/router';
import { finalize } from 'rxjs';

import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { PersonSyncService } from '../../../services/person-sync.service';
/* ------------------------------------------------------------------------------------------------------------------ */

/** A hidden Type (403) or a missing user (404) simply shows no link. */
const SILENT_STATUSES = [403, 404];


/** Links a user to the person mirroring it; renders nothing while it has none. */
@Component({
    selector: 'app-user-person-link',
    standalone: true,
    imports: [RouterLink],
    changeDetection: ChangeDetectionStrategy.OnPush,
    templateUrl: './user-person-link.component.html',
    styleUrls: ['./user-person-link.component.scss']
})
export class UserPersonLinkComponent implements OnInit {

    private readonly personSyncService = inject(PersonSyncService);
    private readonly loaderService = inject(LoaderService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    public readonly userId = input.required<number>();

    protected readonly personId = signal<number | null>(null);

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnInit(): void {
        this.loaderService.show();

        this.personSyncService.getUserPerson(this.userId())
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                finalize(() => this.loaderService.hide())
            )
            .subscribe({
                next: (userPerson) => this.personId.set(userPerson?.person_id ?? null),
                error: (error: HttpErrorResponse) => {
                    if (!SILENT_STATUSES.includes(error?.status)) {
                        this.toastService.error(error?.error?.message);
                    }
                }
            });
    }
}
