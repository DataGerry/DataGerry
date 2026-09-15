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
    inject,
    input,
    output,
    signal
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';

import { Subject } from 'rxjs';
import { debounceTime, distinctUntilChanged, finalize, map, takeUntil } from 'rxjs/operators';

import { CoreModule } from 'src/app/core/core.module';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';

import { AssignableInterface, AssignableInterfacePage, InterfaceRowView } from '../../models/interface-link.types';
import { InterfaceLinkService } from '../../services/interface-link.service';
import { interfaceRowFromAssignable } from '../../utils/interface-row.util';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Interface rows are pulled in pages as the dropdown is scrolled. */
const PAGE_SIZE = 10;

/** Keystrokes are collected for this long before the search hits the backend. */
const SEARCH_DEBOUNCE_MS = 300;


/** One selectable interface row: what the dropdown renders, and the row behind it. */
export interface InterfaceCandidateOption {
    /** Identifies the option in the list; an interface row has no id of its own outside its object. */
    key: string;
    label: string;
    row: InterfaceRowView;
}


/**
 * Selects an interface row the port may still be linked to.
 *
 * Scoped to the port's own object. Rows already linked to the port are left out by the route, so the
 * list itself rules out a double link. An interface row carries no name, so the option is labelled
 * from its addresses and named with the object holding it - without that, several rows of one server
 * read identically.
 */
@Component({
    selector: 'cmdb-interface-candidate-picker',
    templateUrl: './interface-candidate-picker.component.html',
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: true,
    imports: [CoreModule, ReactiveFormsModule]
})
export class InterfaceCandidatePickerComponent implements OnInit {

    private readonly interfaceLinkService = inject(InterfaceLinkService);
    private readonly loaderService = inject(LoaderService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    /** The port being linked. Its own links are what the route excludes. */
    public readonly portId = input.required<number>();

    /** Passed straight to the dropdown, so a host whose layout clips the panel can re-parent it. */
    public readonly appendTo = input('');

    public readonly errorMessage = input('');

    /** The picked row, which the host needs in full to show its addresses. */
    public readonly selectionChange = output<InterfaceRowView | null>();

    /** How many rows the object holds, so the host can explain an empty list. */
    public readonly totalChange = output<number>();

    protected readonly options = signal<InterfaceCandidateOption[]>([]);
    protected readonly isFetching = signal(false);

    protected readonly interfaceControl = new FormControl<string | null>(null);

    /** The dropdown pushes what the user types in here; the list is searched server side. */
    protected readonly searchTerms$ = new Subject<string>();

    /** Cancels the page in flight when the list is rebuilt, so a stale page cannot append to it. */
    private readonly listReset$ = new Subject<void>();

    private searchTerm = '';
    private nextPage = 1;
    private hasMorePages = true;

/* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnInit(): void {
        this.watchSearchTerms();
        this.loadPage(true);
    }

/* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    protected onOptionSelected(option: InterfaceCandidateOption | null): void {
        this.selectionChange.emit(option?.row ?? null);
    }


    /** Reaching the end of the option list pulls the next page in. */
    protected onScrollEnd(): void {
        this.loadPage(false);
    }

/* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    /** Rebuilds the list after a link was written, so the row just linked leaves the candidates. */
    public reload(): void {
        this.clearSelection();
        this.resetPages();
        this.loadPage(false);
    }

/* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    /** A typed term replaces the list with the backend's answer for it, rather than filtering locally. */
    private watchSearchTerms(): void {
        this.searchTerms$
            .pipe(
                map((term) => (term ?? '').trim()),
                debounceTime(SEARCH_DEBOUNCE_MS),
                distinctUntilChanged(),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe((term) => {
                this.searchTerm = term;
                this.resetPages();
                this.loadPage(false);
            });
    }


    private clearSelection(): void {
        this.interfaceControl.setValue(null, { emitEvent: false });
        this.selectionChange.emit(null);
    }


    private resetPages(): void {
        this.listReset$.next();
        this.options.set([]);
        this.nextPage = 1;
        this.hasMorePages = true;
    }


    /**
     * Loads the next page and appends it.
     *
     * Only the list the picker opens with runs behind the modal loader; a search or a further page
     * reports through the dropdown's own spinner, which leaves the user in the field they type in.
     */
    private loadPage(useModalLoader: boolean): void {
        if (this.isFetching() || !this.hasMorePages) {
            return;
        }

        this.isFetching.set(true);

        if (useModalLoader) {
            this.loaderService.show();
        }

        this.interfaceLinkService
            .getAssignableInterfaces(this.portId(), {
                page: this.nextPage,
                page_size: PAGE_SIZE,
                search: this.searchTerm || undefined
            })
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                takeUntil(this.listReset$),
                finalize(() => {
                    this.isFetching.set(false);

                    if (useModalLoader) {
                        this.loaderService.hide();
                    }
                })
            )
            .subscribe({
                next: (page) => this.appendPage(page),
                error: (err) => this.toastService.error(err?.error?.message)
            });
    }


    private appendPage(page: AssignableInterfacePage): void {
        const rows = page?.rows ?? [];
        const loaded = this.options().length + rows.length;

        this.options.update((current) => [...current, ...rows.map((row) => this.toOption(row))]);
        this.hasMorePages = loaded < (page?.total ?? 0);
        this.nextPage += 1;
        this.totalChange.emit(page?.total ?? 0);
    }


    /** The label names the object as well: several rows of one object differ only by their address. */
    private toOption(row: AssignableInterface): InterfaceCandidateOption {
        const view = interfaceRowFromAssignable(row);
        const details = view.details ? ` · ${ view.details }` : '';

        return {
            key: `${ view.interface_object_id }:${ view.interface_multi_data_id }`,
            label: `${ view.label }${ details } — ${ view.objectLabel }`,
            row: view
        };
    }
}
