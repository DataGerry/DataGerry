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
import { HttpHeaders, HttpParams, HttpResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, catchError, map, of, shareReplay, switchMap, tap, throwError } from 'rxjs';

import { ApiCallService, ApiServicePrefix, resp } from 'src/app/services/api-call.service';
import {
    PersonCandidate,
    PersonRefKind,
    PersonSelection,
    PersonRelationTypes,
    PersonRelations,
    personSelectionKey
} from '../models/person.model';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Talks to the /person_relations routes: which types carry the person special types, the selectable
 * persons and groups of a person field, and the memberships and assignments of one person or group.
 */
@Injectable({
    providedIn: 'root'
})
export class PersonRelationsService implements ApiServicePrefix {

    public servicePrefix: string = 'person_relations';

    private readonly api = inject(ApiCallService);

    private readonly headers = new HttpHeaders({ 'Content-Type': 'application/json' });

    /**
     * Candidate lists by kind. Many fields render at once (a table column, a form with several person
     * fields), so they share one request; every membership write drops the cache.
     */
    private readonly candidateCache = new Map<PersonRefKind, { loadedAt: number; candidates$: Observable<Array<PersonCandidate>> }>();

    /** A cached list younger than this is trusted even when it misses a selection (it was deleted). */
    private static readonly CANDIDATE_REFRESH_GRACE_MS = 5000;

    /* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /** The public_id of the CmdbType carrying PERSON and PERSON_GROUP, null while none exists. */
    public getTypes(): Observable<PersonRelationTypes> {
        return this.get<PersonRelationTypes>(`${ this.servicePrefix }/types`).pipe(
            map((types) => ({
                PERSON: types?.PERSON ?? null,
                PERSON_GROUP: types?.PERSON_GROUP ?? null
            }))
        );
    }


    /**
     * The objects a person field of the given kind may select, sorted by label.
     * @param kind what the field selects
     * @param refresh bypass the shared cache, e.g. when an edit form opens
     */
    public getCandidates(kind: PersonRefKind = PersonRefKind.BOTH, refresh: boolean = false): Observable<Array<PersonCandidate>> {
        const normalizedKind = Object.values(PersonRefKind).includes(kind) ? kind : PersonRefKind.BOTH;

        if (refresh || !this.candidateCache.has(normalizedKind)) {
            const candidates$ = this.get<Array<PersonCandidate>>(
                `${ this.servicePrefix }/candidates`,
                new HttpParams().set('kind', normalizedKind)
            ).pipe(
                map((candidates) => Array.isArray(candidates) ? candidates : []),
                catchError((error) => {
                    // A failed lookup must not stick for the rest of the session
                    this.candidateCache.delete(normalizedKind);
                    return throwError(() => error);
                }),
                shareReplay(1)
            );

            this.candidateCache.set(normalizedKind, { loadedAt: Date.now(), candidates$ });
        }

        return this.candidateCache.get(normalizedKind)!.candidates$;
    }


    /**
     * Resolves stored selections to their candidates (label, type), keyed by personSelectionKey. Reads the
     * shared list and reloads it once when a selection is missing from an older list - the person may have
     * been created after the list was cached. A selection still missing then no longer exists.
     */
    public resolveSelections(selections: Array<PersonSelection>): Observable<Map<string, PersonCandidate>> {
        if (!selections?.length) {
            return of(new Map<string, PersonCandidate>());
        }

        const toMap = (candidates: Array<PersonCandidate>) =>
            new Map<string, PersonCandidate>(candidates.map(candidate => [personSelectionKey(candidate), candidate]));
        const isComplete = (byKey: Map<string, PersonCandidate>) =>
            selections.every(selection => byKey.has(personSelectionKey(selection)));

        return this.getCandidates(PersonRefKind.BOTH).pipe(
            map(toMap),
            switchMap((byKey) => {
                const cached = this.candidateCache.get(PersonRefKind.BOTH);
                const isFresh = !!cached
                    && Date.now() - cached.loadedAt < PersonRelationsService.CANDIDATE_REFRESH_GRACE_MS;

                if (isComplete(byKey) || isFresh) {
                    return of(byKey);
                }

                return this.getCandidates(PersonRefKind.BOTH, true).pipe(map(toMap));
            })
        );
    }


    /** Memberships, members and assignments of one person or person group. */
    public getRelations(objectId: number): Observable<PersonRelations> {
        return this.get<PersonRelations>(`${ this.servicePrefix }/${ objectId }`).pipe(
            map((relations) => this.normalizeRelations(relations))
        );
    }


    /** Adds a person to a group's members; answers the group's updated relations. */
    public addMember(groupId: number, personId: number): Observable<PersonRelations> {
        return this.api.callPost<PersonRelations>(
            `${ this.servicePrefix }/${ groupId }/members`,
            { person_id: personId },
            this.options()
        ).pipe(
            map((response: HttpResponse<PersonRelations>) => this.normalizeRelations(this.unwrap(response?.body))),
            tap(() => this.clearCandidateCache())
        );
    }


    /** Removes a person from a group's members; answers the group's updated relations. */
    public removeMember(groupId: number, personId: number): Observable<PersonRelations> {
        return this.api.callDelete<PersonRelations>(
            `${ this.servicePrefix }/${ groupId }/members/${ personId }`,
            this.options()
        ).pipe(
            map((response: HttpResponse<PersonRelations>) => this.normalizeRelations(this.unwrap(response?.body))),
            tap(() => this.clearCandidateCache())
        );
    }


    public clearCandidateCache(): void {
        this.candidateCache.clear();
    }

    /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private get<T>(route: string, params: HttpParams = new HttpParams()): Observable<T> {
        return this.api.callGet<T>(route, this.options(params)).pipe(
            map((response: HttpResponse<T>) => this.unwrap<T>(response?.body))
        );
    }


    private options(params: HttpParams = new HttpParams()) {
        return { headers: this.headers, params, observe: resp };
    }


    private normalizeRelations(relations: PersonRelations | null | undefined): PersonRelations {
        return {
            ref_type: relations?.ref_type,
            memberships: relations?.memberships ?? [],
            members: relations?.members ?? [],
            assignments: relations?.assignments ?? []
        };
    }


    /** The routes answer a plain DefaultResponse; a `result` envelope is tolerated all the same. */
    private unwrap<T>(body: unknown): T {
        if (body && typeof body === 'object' && !Array.isArray(body) && 'result' in body) {
            return (body as { result: T }).result;
        }

        return body as T;
    }
}
