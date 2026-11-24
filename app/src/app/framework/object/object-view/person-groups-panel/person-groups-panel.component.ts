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
import {
    ChangeDetectionStrategy,
    Component,
    DestroyRef,
    OnInit,
    TemplateRef,
    computed,
    inject,
    input,
    signal,
    viewChild
} from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { finalize } from 'rxjs';

import { CoreModule } from 'src/app/core/core.module';
import { TableModule } from 'src/app/layout/table/table.module';
import { Column } from 'src/app/layout/table/table.types';
import { PersonPickerComponent } from 'src/app/core/components/person-picker/person-picker.component';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { PermissionService } from 'src/app/modules/auth/services/permission.service';
import { RenderResult } from 'src/app/framework/models/cmdb-render';
import {
    PersonGroupRow,
    PersonGroupsAnswer,
    PersonGroupsChange,
    PersonKind,
    PersonSelection,
    personDisplayLabel
} from 'src/app/framework/models/person-selector';
import { ObjectPersonGroupsService } from 'src/app/framework/services/object-person-groups.service';
import { isSyncedPerson } from 'src/app/framework/utils/synced-object.util';
/* ------------------------------------------------------------------------------------------------------------------ */

const OBJECT_EDIT_RIGHT = 'base.framework.object.edit';

/** 404 and 403 mean the object is no person, or its Type is hidden: there is no panel to show. */
const SILENT_STATUSES = [403, 404];


/** The person groups of a person object, joined and left from the person's side. */
@Component({
    selector: 'cmdb-person-groups-panel',
    standalone: true,
    imports: [CoreModule, PersonPickerComponent, ReactiveFormsModule, RouterLink, TableModule],
    changeDetection: ChangeDetectionStrategy.OnPush,
    templateUrl: './person-groups-panel.component.html',
    styleUrls: ['./person-groups-panel.component.scss']
})
export class PersonGroupsPanelComponent implements OnInit {

    private readonly personGroupsService = inject(ObjectPersonGroupsService);
    private readonly permissionService = inject(PermissionService);
    private readonly loaderService = inject(LoaderService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    public readonly renderResult = input.required<RenderResult>();

    protected readonly groupKinds: ReadonlyArray<PersonKind> = ['PERSON_GROUP'];

    protected readonly canEdit = this.permissionService.hasRight(OBJECT_EDIT_RIGHT)
        || this.permissionService.hasExtendedRight(OBJECT_EDIT_RIGHT);

    protected readonly groups = signal<PersonSelection[]>([]);
    protected readonly isAvailable = signal(false);
    protected readonly isSaving = signal(false);

    protected readonly addControl = new FormControl<number | null>(null);

    private readonly pickedGroupId = toSignal(this.addControl.valueChanges, { initialValue: null });

    protected readonly canAdd = computed(() => this.pickedGroupId() !== null && !this.isSaving());

    /** A synced person's mapped groups follow its user while the group sync runs. */
    protected readonly rows = computed<PersonGroupRow[]>(() => {
        const result = this.renderResult();
        const locksMappedGroups = isSyncedPerson(result) && result.object_information.group_sync_active === true;

        return this.groups().map(group => ({
            object_id: group.object_id,
            label: personDisplayLabel({ ...group, active: true }),
            type_label: group.type_label,
            inactive: group.active === false,
            managed: locksMappedGroups && group.system_ref?.kind === 'user_group'
        }));
    });

    private readonly nameTemplate = viewChild.required<TemplateRef<unknown>>('nameTemplate');
    private readonly statusTemplate = viewChild.required<TemplateRef<unknown>>('statusTemplate');
    private readonly actionsTemplate = viewChild.required<TemplateRef<unknown>>('actionsTemplate');

    protected readonly columns = computed<Column[]>(() => {
        const columns: Column[] = [
            { display: 'Group', name: 'label', data: 'label', sortable: false, template: this.nameTemplate() },
            { display: 'Type', name: 'type_label', data: 'type_label', sortable: false },
            { display: 'Status', name: 'status', data: 'managed', sortable: false, template: this.statusTemplate() }
        ];

        if (this.canEdit) {
            columns.push({
                display: 'Actions',
                name: 'actions',
                data: 'object_id',
                sortable: false,
                template: this.actionsTemplate(),
                cssClasses: ['text-center']
            });
        }

        return columns;
    });

    /** A synced person joins a mapped group only through its user while the group sync runs. */
    protected readonly isLockedGroup = (group: PersonSelection): boolean => {
        const result = this.renderResult();

        return isSyncedPerson(result)
            && result.object_information.group_sync_active === true
            && group.system_ref?.kind === 'user_group';
    };

    /** The groups already joined are not offered again. */
    protected readonly memberIds = computed(() => this.groups().map(group => group.object_id));

    private get personId(): number {
        return this.renderResult().object_information.object_id;
    }

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnInit(): void {
        this.loadGroups();
    }

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    protected onAdd(): void {
        const groupId = this.addControl.value;

        if (groupId === null || this.isSaving()) {
            return;
        }

        this.changeGroups({ add: [groupId] }, () => this.addControl.reset());
    }


    protected onRemove(row: PersonGroupRow): void {
        if (row.managed || this.isSaving()) {
            return;
        }

        this.changeGroups({ remove: [row.object_id] });
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private loadGroups(): void {
        this.loaderService.show();

        this.personGroupsService.getPersonGroups(this.personId)
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                finalize(() => this.loaderService.hide())
            )
            .subscribe({
                next: (groups) => {
                    this.groups.set(groups);
                    this.isAvailable.set(true);
                },
                error: (error: HttpErrorResponse) => {
                    if (!SILENT_STATUSES.includes(error?.status)) {
                        this.toastService.error(error?.error?.message);
                    }
                }
            });
    }


    private changeGroups(change: PersonGroupsChange, onDone?: () => void): void {
        this.isSaving.set(true);
        this.loaderService.show();

        this.personGroupsService.changePersonGroups(this.personId, change)
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                finalize(() => {
                    this.isSaving.set(false);
                    this.loaderService.hide();
                })
            )
            .subscribe({
                next: (answer: PersonGroupsAnswer) => {
                    this.groups.set(answer?.results ?? []);
                    onDone?.();

                    if (answer?.failed?.length) {
                        this.toastService.error(`These person groups could not be changed: ${ answer.failed.join(', ') }`);
                        return;
                    }

                    this.toastService.success('The person groups were updated!');
                },
                error: (error: HttpErrorResponse) => this.toastService.error(error?.error?.message)
            });
    }
}
