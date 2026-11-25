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
import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';
import { finalize } from 'rxjs';

import { CoreModule } from 'src/app/core/core.module';
import { DgModalComponent } from 'src/app/core/components/modal/dg-modal.component';
import { PersonPickerComponent } from 'src/app/core/components/person-picker/person-picker.component';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { TypeService } from 'src/app/framework/services/type.service';
import { SpecialType } from 'src/app/framework/models/special-type';
import { PersonKind } from 'src/app/framework/models/person-selector';
import { GroupMapTarget, GroupMappingRequest, SyncSelectOption } from '../../../models/person-sync';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Picks what a user group is mapped to: an existing person group, or a new one created in a PERSON_GROUP Type. */
@Component({
    selector: 'app-group-map-modal',
    standalone: true,
    imports: [CoreModule, DgModalComponent, PersonPickerComponent, ReactiveFormsModule],
    changeDetection: ChangeDetectionStrategy.OnPush,
    templateUrl: './group-map-modal.component.html',
})
export class GroupMapModalComponent {

    public readonly activeModal = inject(NgbActiveModal);
    private readonly typeService = inject(TypeService);
    private readonly loaderService = inject(LoaderService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    public readonly groupLabel = signal('');

    protected readonly personGroupKinds: ReadonlyArray<PersonKind> = ['PERSON_GROUP'];
    protected readonly target = signal<GroupMapTarget>('existing');
    protected readonly typeOptions = signal<SyncSelectOption[]>([]);

    protected readonly personGroupControl = new FormControl<number | null>(null, Validators.required);
    protected readonly typeControl = new FormControl<number | null>(null, Validators.required);

    private readonly personGroupId = toSignal(this.personGroupControl.valueChanges, { initialValue: null });
    private readonly typeId = toSignal(this.typeControl.valueChanges, { initialValue: null });
    private typesLoaded = false;

    protected readonly canSubmit = computed(() =>
        this.target() === 'existing' ? this.personGroupId() !== null : this.typeId() !== null
    );

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    protected onChooseNew(): void {
        this.target.set('new');

        if (!this.typesLoaded) {
            this.loadTypes();
        }
    }


    protected onSubmit(): void {
        if (!this.canSubmit()) {
            return;
        }

        const request: GroupMappingRequest = this.target() === 'existing'
            ? { person_group_id: this.personGroupControl.value }
            : { type_id: this.typeControl.value };

        this.activeModal.close(request);
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private loadTypes(): void {
        this.typesLoaded = true;
        this.loaderService.show();

        this.typeService.getTypes({
            filter: { special_type: SpecialType.PERSON_GROUP },
            limit: 0,
            sort: 'label',
            order: 1,
            page: 1
        })
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                finalize(() => this.loaderService.hide())
            )
            .subscribe({
                next: (response) => this.typeOptions.set((response?.results ?? []).map(type => ({
                    public_id: type.public_id,
                    label: type.label || type.name
                }))),
                error: (error: HttpErrorResponse) => {
                    this.typesLoaded = false;
                    this.toastService.error(error?.error?.message);
                }
            });
    }
}
