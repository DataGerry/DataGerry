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
import { DestroyRef, Injectable, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { EMPTY, Observable, Subject } from 'rxjs';
import { catchError, finalize, switchMap, takeUntil } from 'rxjs/operators';

import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { CablingGraph, CablingResponse } from '../models/cabling.types';
import { EMPTY_CABLING_GRAPH, graphFromRing, graphWithExpansion, revealedObjectIds } from '../utils/cabling-graph.util';
import { CablingService } from './cabling.service';
/* ------------------------------------------------------------------------------------------------------------------ */

/** What one cabling view has drawn, and the two requests that grow it. Provided per view. */
@Injectable()
export class CablingViewStore {

    private readonly cablingService = inject(CablingService);
    private readonly loaderService = inject(LoaderService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    private readonly graphState = signal<CablingGraph>(EMPTY_CABLING_GRAPH);
    private readonly expandingState = signal<ReadonlySet<number>>(new Set());
    private readonly failedState = signal(false);
    private readonly loadedState = signal(false);

    /** Every load passes through here, so it also cancels what an earlier object still had in flight. */
    private readonly ringRequests = new Subject<number | null>();
    private readonly loadedSubject = new Subject<void>();
    private readonly revealedSubject = new Subject<number[]>();
    private objectId: number | null = null;

    public readonly graph = this.graphState.asReadonly();
    public readonly expandingPortIds = this.expandingState.asReadonly();
    public readonly loadFailed = this.failedState.asReadonly();
    public readonly loaded = this.loadedState.asReadonly();

    /** Fires once a ring is on the canvas, so the view can fit it. */
    public readonly loaded$ = this.loadedSubject.asObservable();

    /** Fires with the objects an expansion added, so the view can bring them on screen. */
    public readonly revealed$ = this.revealedSubject.asObservable();

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    constructor() {
        // switchMap: a second object replaces a ring still in flight instead of racing it.
        this.ringRequests
            .pipe(
                switchMap((objectId) => (objectId == null ? EMPTY : this.readRing(objectId))),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe((response) => {
                this.graphState.set(graphFromRing(response));
                this.loadedState.set(true);
                this.loadedSubject.next();
            });
    }

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /** Starts over on this object's ring; whatever an earlier expansion is still reading is dropped. */
    public load(objectId: number | null): void {
        this.objectId = objectId;
        this.graphState.set(EMPTY_CABLING_GRAPH);
        this.expandingState.set(new Set());
        this.failedState.set(false);
        this.loadedState.set(false);
        this.ringRequests.next(objectId);
    }


    /** Back to the first ring of the same object. */
    public reload(): void {
        this.load(this.objectId);
    }


    /** Adds the object at the far end of this port. Asking twice for one port is ignored. */
    public expandPort(portId: number): void {
        if (this.expandingState().has(portId)) {
            return;
        }

        this.expandingState.update((ids) => new Set(ids).add(portId));
        this.loaderService.show();

        this.cablingService.getPortCabling(portId)
            .pipe(
                catchError(() => {
                    this.toastService.error('The cabling of this port could not be loaded.');

                    return EMPTY;
                }),
                finalize(() => {
                    this.loaderService.hide();
                    this.expandingState.update((ids) => {
                        const remaining = new Set(ids);
                        remaining.delete(portId);

                        return remaining;
                    });
                }),
                takeUntil(this.ringRequests),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe((response) => this.applyExpansion(response, portId));
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    private readRing(objectId: number): Observable<CablingResponse> {
        this.loaderService.show();

        return this.cablingService.getObjectCabling(objectId).pipe(
            // Reported here: an error reaching the outer stream would end it, and no later object would load.
            catchError(() => {
                this.failedState.set(true);
                this.toastService.error('The cabling could not be loaded.');

                return EMPTY;
            }),
            finalize(() => this.loaderService.hide())
        );
    }


    private applyExpansion(response: CablingResponse, portId: number): void {
        const graph = this.graphState();
        const added = revealedObjectIds(graph, response);

        if (!response.nodes.length) {
            this.toastService.info('This port leads to no other object.');

            return;
        }

        this.graphState.set(graphWithExpansion(graph, response, portId));

        if (added.length) {
            this.revealedSubject.next(added);
        }
    }
}
