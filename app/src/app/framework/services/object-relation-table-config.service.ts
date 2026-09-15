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
import { Injectable, inject } from '@angular/core';
import { Observable, catchError, of } from 'rxjs';

import { RelationService } from './relaion.service';
import { TableService } from '../../layout/table/table.service';
import { convertResourceURL } from '../../management/user-settings/services/user-settings.service';

import { CmdbRelation, RelationField } from '../models/relation.model';
import { ObjectRelationTab } from '../models/object-relation.model';
import { TableStatePayload } from '../../layout/table/table.types';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Backs the customizable table of the relation tabs in the object view: it resolves
 * the relation definition the field columns are derived from and addresses the saved
 * table states.
 *
 * A relation tab is not a page of its own, so its states are stored per relation and
 * role instead of per object - a layout saved on one object applies to the same
 * relation on every other one.
 */
@Injectable({
    providedIn: 'root'
})
export class ObjectRelationTableConfigService {

    /** Payload the table states of a relation tab are stored in. */
    public static readonly STATE_PAYLOAD_ID = 'object-relation-tab';

    private readonly relationService = inject(RelationService);
    private readonly tableService = inject(TableService);

    /* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /**
     * Relation definition the field columns of a tab are derived from.
     */
    public getRelation(relationID: number): Observable<CmdbRelation | null> {
        if (!relationID) {
            return of(null);
        }

        return this.relationService.getRelation(relationID);
    }


    /**
     * Field definitions in the order the relation builder placed them. Fields that
     * are not part of any section are appended.
     */
    public getOrderedFields(relation: CmdbRelation | null): Array<RelationField> {
        const fields = relation?.fields ?? [];

        if (!fields.length) {
            return [];
        }

        const byName = new Map(fields.map(field => [field.name, field]));
        const ordered: Array<RelationField> = [];

        for (const section of relation?.sections ?? []) {
            for (const sectionField of section?.fields ?? []) {
                // A section holds field names at rest and field objects while the builder is open.
                const fieldName = typeof sectionField === 'string' ? sectionField : sectionField?.name;
                const field = byName.get(fieldName);

                if (field) {
                    ordered.push(field);
                    byName.delete(fieldName);
                }
            }
        }

        return [...ordered, ...byName.values()];
    }


    /** Url the table states of a tab are stored under. */
    public getStateUrl(tab: ObjectRelationTab): string {
        return `/framework/object-relations/${tab.relation_id}-${tab.role}`;
    }


    /**
     * Saved states of a tab. Emits `undefined` while no layout was saved for this
     * relation yet, which is the regular case rather than a failure.
     */
    public getStatePayload(tab: ObjectRelationTab): Observable<TableStatePayload | undefined> {
        const resource = convertResourceURL(this.getStateUrl(tab));

        return this.tableService.getTableStatePayload(resource, ObjectRelationTableConfigService.STATE_PAYLOAD_ID)
            .pipe(catchError(() => of(undefined)));
    }
}
