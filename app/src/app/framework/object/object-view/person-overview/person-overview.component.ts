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
import { Component, Input, OnChanges, OnDestroy, SimpleChanges, inject } from '@angular/core';

import { Observable, ReplaySubject, concat, finalize, last, switchMap, takeUntil } from 'rxjs';

import { ToastService } from 'src/app/layout/toast/toast.service';
import { PermissionService } from 'src/app/modules/auth/services/permission.service';
import { ObjectChangeNotifierService } from 'src/app/framework/services/object-change-notifier.service';
import { PersonRelationsService } from 'src/app/framework/services/person-relations.service';
import { SpecialType } from 'src/app/framework/models/special-type';
import {
    PersonAssignment,
    PersonCandidate,
    PersonRefKind,
    PersonRelations
} from 'src/app/framework/models/person.model';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Adding and removing members writes the group object, so it answers to the object edit right. */
export const PERSON_MEMBERSHIP_EDIT_RIGHT = 'base.framework.object.edit';

/**
 * The section a PERSON or PERSON_GROUP object brings below its attributes.
 *
 * A person lists the groups it belongs to (with remove buttons and an "Add to group" picker); a group lists
 * its member persons (with remove buttons and an "Add persons" picker). Both list the objects that point
 * at them through a person field. Membership is stored on the group only, so every write addresses the group.
 */
@Component({
    selector: 'cmdb-person-overview',
    templateUrl: './person-overview.component.html',
    styleUrls: ['./person-overview.component.scss'],
    standalone: false
})
export class PersonOverviewComponent implements OnChanges, OnDestroy {

    /** public_id of the person or group on screen. */
    @Input() public publicId: number;

    /** Which side the object is on. */
    @Input() public specialType: SpecialType;

    private readonly personRelationsService = inject(PersonRelationsService);
    private readonly objectChanges = inject(ObjectChangeNotifierService);
    private readonly toastService = inject(ToastService);
    private readonly permissionService = inject(PermissionService);

    private readonly unsubscribe = new ReplaySubject<void>();
    private readonly reload = new ReplaySubject<void>();

    /** The buttons are hidden without the right, and every write path re-checks it before it acts. */
    public readonly canEdit: boolean = this.permissionService.hasRight(PERSON_MEMBERSHIP_EDIT_RIGHT)
        || this.permissionService.hasExtendedRight(PERSON_MEMBERSHIP_EDIT_RIGHT);

    public relations: PersonRelations | null = null;
    public loading: boolean = false;
    public saving: boolean = false;
    public hasError: boolean = false;

    /** Selectable groups (person view) or persons (group view), without the ones already linked. */
    public candidates: Array<PersonCandidate> = [];
    public candidatesLoading: boolean = false;
    public selectedGroupId: number | null = null;
    public selectedPersonIds: Array<number> = [];

    private allCandidates: Array<PersonCandidate> = [];

    /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    constructor() {
        this.reload.pipe(
            switchMap(() => this.loadRelations()),
            takeUntil(this.unsubscribe)
        ).subscribe();
    }


    public ngOnChanges(changes: SimpleChanges): void {
        if ((changes['publicId'] || changes['specialType']) && this.publicId) {
            this.relations = null;
            this.selectedGroupId = null;
            this.selectedPersonIds = [];
            this.reload.next();

            if (this.canEdit) {
                this.loadCandidates();
            }
        }
    }


    public ngOnDestroy(): void {
        this.unsubscribe.next();
        this.unsubscribe.complete();
    }

    /* ---------------------------------------------------- GETTERS ----------------------------------------------------- */

    public get isPerson(): boolean {
        return this.specialType === SpecialType.PERSON;
    }


    public get isGroup(): boolean {
        return this.specialType === SpecialType.PERSON_GROUP;
    }


    /** The groups of a person, or the members of a group. */
    public get linked(): Array<PersonCandidate> {
        if (!this.relations) {
            return [];
        }

        return this.isPerson ? this.relations.memberships : this.relations.members;
    }


    public get assignments(): Array<PersonAssignment> {
        return this.relations?.assignments ?? [];
    }

    /* ---------------------------------------------------- ACTIONS ----------------------------------------------------- */

    /** Person view: adds the person on screen to the picked group. */
    public addToGroup(): void {
        if (!this.canEdit || !this.isPerson || !this.selectedGroupId || this.saving) {
            return;
        }

        const groupId = this.selectedGroupId;
        this.write(
            this.personRelationsService.addMember(groupId, this.publicId),
            groupId,
            'The person was added to the group.'
        );
    }


    /** Group view: adds every picked person, one request after the other. */
    public addPersons(): void {
        if (!this.canEdit || !this.isGroup || !this.selectedPersonIds.length || this.saving) {
            return;
        }

        const requests = this.selectedPersonIds.map(personId => this.personRelationsService.addMember(this.publicId, personId));
        const count = requests.length;

        this.write(
            concat(...requests).pipe(last()),
            this.publicId,
            count === 1 ? 'The person was added to the group.' : `${ count } persons were added to the group.`
        );
    }


    /** Removes the membership the row stands for - the person from the row's group, or the row's person. */
    public removeLinked(entry: PersonCandidate): void {
        if (!this.canEdit || this.saving || !entry) {
            return;
        }

        const groupId = this.isPerson ? entry.id : this.publicId;
        const personId = this.isPerson ? this.publicId : entry.id;

        this.write(
            this.personRelationsService.removeMember(groupId, personId),
            groupId,
            'The membership was removed.'
        );
    }


    public trackById(_: number, entry: PersonCandidate): number {
        return entry.id;
    }

    /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    /**
     * Runs one membership write. The routes answer the group's relations: a group view takes them as they
     * are, a person view reloads its own. The written group is announced so an open view of it re-reads.
     */
    private write(request: Observable<PersonRelations>, groupId: number, successMessage: string): void {
        this.saving = true;

        request.pipe(
            finalize(() => this.saving = false),
            takeUntil(this.unsubscribe)
        ).subscribe({
            next: (groupRelations) => {
                this.toastService.success(successMessage);
                this.selectedGroupId = null;
                this.selectedPersonIds = [];

                if (this.isGroup) {
                    this.relations = groupRelations;
                    this.refreshCandidateList();
                } else {
                    this.reload.next();
                }

                this.objectChanges.notifyChanged(groupId);
            },
            error: (error) => {
                this.toastService.error(error?.error?.message ?? 'The membership could not be changed.');
                this.reload.next();
            }
        });
    }


    private loadRelations(): Observable<never> {
        this.loading = true;
        this.hasError = false;

        return new Observable<never>((subscriber) => {
            const subscription = this.personRelationsService.getRelations(this.publicId).subscribe({
                next: (relations) => {
                    this.relations = relations;
                    this.loading = false;
                    this.refreshCandidateList();
                    subscriber.complete();
                },
                error: (error) => {
                    this.loading = false;
                    this.hasError = true;
                    this.toastService.error(error?.error?.message ?? 'The person relations could not be loaded.');
                    subscriber.complete();
                }
            });

            return () => subscription.unsubscribe();
        });
    }


    private loadCandidates(): void {
        const kind = this.isPerson ? PersonRefKind.PERSON_GROUP : this.isGroup ? PersonRefKind.PERSON : null;

        if (!kind) {
            return;
        }

        this.candidatesLoading = true;
        this.personRelationsService.getCandidates(kind, true).pipe(
            finalize(() => this.candidatesLoading = false),
            takeUntil(this.unsubscribe)
        ).subscribe({
            next: (candidates) => {
                this.allCandidates = candidates;
                this.refreshCandidateList();
            },
            error: () => {
                this.allCandidates = [];
                this.refreshCandidateList();
            }
        });
    }


    /** Offers only what is not linked yet; recomputed whenever the links or the candidates change. */
    private refreshCandidateList(): void {
        const linkedIds = new Set(this.linked.map(entry => entry.id));
        this.candidates = this.allCandidates.filter(candidate => !linkedIds.has(candidate.id) && candidate.id !== this.publicId);
    }
}
