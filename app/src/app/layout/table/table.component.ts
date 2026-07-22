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
    AfterViewInit,
    ChangeDetectionStrategy,
    Component,
    ElementRef,
    EventEmitter,
    inject,
    Input,
    isDevMode,
    NgZone,
    OnDestroy,
    OnInit,
    Output,
    Renderer2,
    TemplateRef,
    ViewChild,
    ViewEncapsulation
} from '@angular/core';
import { Router, NavigationEnd } from '@angular/router';
import { UntypedFormControl, UntypedFormGroup } from '@angular/forms';

import { Observable, ReplaySubject, Subscription, merge, takeUntil } from 'rxjs';

import { TableService } from './table.service';

import { Column, GroupRowsBy, Sort, SortDirection, TableState } from './table.types';
import { PageLengthEntry } from './components/table-page-size/table-page-size.component';
import { ToastService } from '../toast/toast.service';
import { CdkDragDrop, moveItemInArray } from '@angular/cdk/drag-drop';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'cmdb-table',
    templateUrl: './table.component.html',
    styleUrls: ['./table.component.scss'],
    encapsulation: ViewEncapsulation.None,
    changeDetection: ChangeDetectionStrategy.Default,
    standalone: false
})
export class TableComponent<T> implements OnInit, AfterViewInit, OnDestroy {
    // `ViewChild` for accessing the complete table container
    @ViewChild('container', { static: true }) public containerRef: ElementRef;
    // `ViewChild` for accessing the table html element
    @ViewChild('table', { static: true }) public tableRef: ElementRef;
    // `ViewChild` for the horizontal scroll region that holds the table
    @ViewChild('scroll') private scrollRef: ElementRef<HTMLElement>;
    // `ViewChild` for the floating scrollbar track pinned to the bottom of the viewport
    @ViewChild('stickyScrollbar') private stickyScrollbarRef: ElementRef<HTMLElement>;
    // `ViewChild` for the draggable thumb inside the floating scrollbar
    @ViewChild('stickyThumb') private stickyThumbRef: ElementRef<HTMLElement>;

    private readonly renderer = inject(Renderer2);
    private readonly zone = inject(NgZone);
    private resizeObserver?: ResizeObserver;
    private scrollCleanups: Array<() => void> = [];
    private dragCleanup?: () => void;
    // Minimum thumb width in px; must match `min-width` of `.table-sticky-scrollbar__thumb`.
    private readonly MIN_THUMB_WIDTH = 28;

    private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

   // Represents row from reports overview (for row with selected fields empty)
    @Input() reportRowValidationClass: (item: any) => { [className: string]: boolean };
    
    // Array of possible custom buttons displayed in header
    @Input() public customButtons: Array<TemplateRef<any>>;
    // html table id
    @Input() public id: string = `table-${Math.random().toString(36).substring(10)}`;

    @Input() public isViewAndEditRequired: boolean = false;

    // Message which will be shown if no data are in the table
    @Input() public emptyMessage: string = 'No data to display!';

    // Component wide debounce time
    @Input() public debounceTime: number = 500;

    // Is the table data currently in loading
    @Input() public loading: boolean = false;

    // Should the loading spinner be loaded
    @Input() public loadingEnabled: boolean = true;

    // Column holder for reset
    @Input() public initialVisibleColumns: Array<string> = [];

    public columns: Array<Column> = [];

    @Input('columns')
    public set Columns(columns: Array<Column>) {
        this.columns = columns;
        this.buildColumnSearchForm();
    }

    // Column search form group
    public columnSearchForm: UntypedFormGroup;

    // Column search columnSearchForm group
    public columnSearchIconHidden: boolean = false;

    // Column search input enabled
    @Input() public columnSearchEnabled: boolean = false;

    // Event Emitter for column search input change
    @Output() public columnSearchChange: EventEmitter<any[]> = new EventEmitter<any[]>();

    // Items or data which will be inserted into the tbody
    @Input() public items: Array<T> = [];

    // Total number of items which exists for this table
    @Input() public totalItems: number = 0;

    // Is row selected enabled
    @Input() public selectEnabled: boolean = false;

    // Selected items
    @Input() public selectedItems: Array<T> = [];

    // Event emitter when selected items changed
    @Output() public selectedChange: EventEmitter<Array<T>> = new EventEmitter<Array<T>>();

    // Initial page site
    public initPage: number = 1;

    @Input('initPage')
    public set InitPage(page: number) {
        this.initPage = page;
        this.page = page;
    }

    // Current displayed page number
    public page: number = this.initPage;

    @Input('page')
    public set Page(page: number) {
        this.page = page;
    }

    // Pagination enabled
    @Input() public paginationEnabled: boolean = true;

    // Event Emitter when the current page was changed
    @Output() public pageChange: EventEmitter<number> = new EventEmitter<number>();

    // Is a switching of the page size possible
    @Input() public pageSizeEnabled: boolean = true;

    // Current page size
    @Input() public pageSize: number = 10;

    // Possible page size list
    @Input() public pageSizeList: Array<PageLengthEntry>;

    // Event Emitter when the page size changed
    @Output() public pageSizeChange: EventEmitter<number> = new EventEmitter<number>();

    // Search input enabled
    @Input() public searchEnabled: boolean = true;

    // Event Emitter for search input change
    @Output() public searchChange: EventEmitter<string> = new EventEmitter<string>();

    // Info display enabled
    @Input() public infoEnabled: boolean = true;

    // Row group parameter
    @Input() public groupRowsBy: GroupRowsBy;

    // Are columns toggleable
    @Input() public toggleable: boolean = false;

    // Dynamic list of css classes for the table body
    @Input() public bodyClasses: Array<string> = [];

    // Dynamic list of css classes for column heads
    @Input() public columnClasses: Array<string> = [];

    // Dynamic list of css classes for rows
    @Input() public rowClasses: Array<string> = [];

    // Visibility change emitter
    @Output() public columnVisibilityChange: EventEmitter<Column> = new EventEmitter<Column>();

    // Sorting enabled
    @Input() public sortable: boolean = true;

    // Sort change emitter
    @Output() public sortChange: EventEmitter<Sort> = new EventEmitter<Sort>();

    // Table sort value
    public sort: Sort = { name: null, order: SortDirection.ASCENDING };

    // Sort input setter
    @Input('sort')
    public set Sort(value: Sort) {
        this.sort = value;
    }

    // Event emitter when any config was changed
    @Input() public stateEnabled: boolean = false;

    // List of possible table configs
    @Input() public tableStates: Array<TableState> = [];

    // Current user table config
    @Input() public tableState: TableState;

    // Event emitter when any config was changed
    @Output() public stateChange: EventEmitter<TableState> = new EventEmitter<TableState>();

    // Config save emit
    @Output() public stateSelect: EventEmitter<TableState> = new EventEmitter<TableState>();
    @Output() public stateSave: EventEmitter<TableState> = new EventEmitter<TableState>();
    @Output() public stateUpdate: EventEmitter<TableState> = new EventEmitter<TableState>();
    @Output() public stateDelete: EventEmitter<TableState> = new EventEmitter<TableState>();
    @Output() public stateReset: EventEmitter<void> = new EventEmitter<void>();

    @Input() enableObjectReferenceLinks: boolean = false; // To enable hover pointer and routing
    @Input() referenceViewPath: string[] = []; // Base route for navigation

    // Added input to enable draggable rows
    @Input() public draggableEnabled: boolean = false;

    // Added output to emit reordered items
    @Output() public orderChange: EventEmitter<T[]> = new EventEmitter<T[]>();

<<<<<<< HEAD
    public trackById = (index: number, item: any) => item.id ?? index;
=======
    public trackById = (_index: number, item: any) => item?.public_id ?? item?.id ?? item;
>>>>>>> origin/version-3.2
    public trackByName = (index: number, column: any) => column.name ?? index;

    public get joinedRowClasses(): string {
        return this.rowClasses?.join(' ') ?? '';
    }

    ASC: number = SortDirection.ASCENDING;
    DSC: number = SortDirection.DESCENDING;
    routerSubscription: Subscription | undefined;

    /* ------------------------------------------------------------------------------------------------------------------ */
    /*                                                     LIFE CYCLE                                                     */
    /* ------------------------------------------------------------------------------------------------------------------ */

    public constructor(private tableService: TableService, 
        private router: Router, private toastService: ToastService,) {
        this.resetSelectedItems()
    }


    public ngOnInit(): void {
        this.configChangeObservable.pipe(takeUntil(this.subscriber))
            .subscribe({
                next: () => {
                    this.tableState = {
                        name: '',
                        page: this.page,
                        pageSize: this.pageSize,
                        sort: this.sort,
                        visibleColumns: this.columns.filter(c => !c.hidden).map(c => c.name)
                    } as TableState;

                    if (this.stateEnabled) {
                        this.tableService.setCurrentTableState(this.router.url, this.id, this.tableState);
                        this.stateChange.emit(this.tableState);
                    }
                },
                error: (error) => {
                    this.toastService.error(error?.error?.message);
                }
            }
            );

        if (isDevMode()) {
            this.pageSizeChange.asObservable().pipe(takeUntil(this.subscriber)).subscribe((size: number) => {
                console.log(`[TableEvent] Page size changed to: ${size}`);
            });

            this.pageChange.asObservable().pipe(takeUntil(this.subscriber)).subscribe((page: number) => {
                console.log(`[TableEvent] Page changed to: ${page}`);
            });

            this.searchChange.asObservable().pipe(takeUntil(this.subscriber)).subscribe((search: string) => {
                console.log(`[TableEvent] Search input changed to: ${search}`);
            });

            this.selectedChange.asObservable().pipe(takeUntil(this.subscriber)).subscribe((selected: Array<T>) => {
                console.log(`[TableEvent] Selected rows changed to: ${selected} `);
            });

            this.sortChange.asObservable().pipe(takeUntil(this.subscriber)).subscribe((sort: Sort) => {
                console.log(`[TableEvent] Sort changed to: ${sort}`);
            });
        }

        this.buildColumnSearchForm();
    }


    public ngAfterViewInit(): void {
        const scrollEl = this.scrollRef?.nativeElement;
        const barEl = this.stickyScrollbarRef?.nativeElement;

        if (!scrollEl || !barEl) {
            return;
        }

        const thumbEl = this.stickyThumbRef?.nativeElement;

        // Scrollbar rendering only reads layout and writes styles/classes; keep it out
        // of change detection so scrolling and dragging stay smooth.
        this.zone.runOutsideAngular(() => {
            this.scrollCleanups.push(
                this.renderer.listen(scrollEl, 'scroll', () => this.renderStickyScrollbar())
            );

            if (thumbEl) {
                this.scrollCleanups.push(
                    this.renderer.listen(thumbEl, 'pointerdown', (event: PointerEvent) => this.onThumbDragStart(event))
                );
            }

            if (typeof ResizeObserver !== 'undefined') {
                this.resizeObserver = new ResizeObserver(() => this.renderStickyScrollbar());
                this.resizeObserver.observe(scrollEl);

                if (this.tableRef?.nativeElement) {
                    this.resizeObserver.observe(this.tableRef.nativeElement);
                }
            }

            this.renderStickyScrollbar();
        });
    }


    public ngOnDestroy(): void {
        this.subscriber?.next();
        this.subscriber?.complete();
        this.routerSubscription?.unsubscribe();
        this.scrollCleanups.forEach((cleanup) => cleanup());
        this.dragCleanup?.();
        this.resizeObserver?.disconnect();
    }


    /* ------------------------------------------------- HELPER METHODS ------------------------------------------------- */

    /**
     * Reseting the selected Items
     */
    private resetSelectedItems(): void {
        this.routerSubscription = this.router.events.subscribe((event) => {
            if (event instanceof NavigationEnd) {
                this.selectedItems = [];
            }
        });
    }


    /**
     * Get any kind of table config change as observable
     */
    private get configChangeObservable(): Observable<any> {
        return merge(
            this.pageChange.asObservable(),
            this.columnVisibilityChange.asObservable(),
            this.sortChange.asObservable(),
            this.pageSizeChange.asObservable()
        );
    }


    /**
     * Position and size the custom scrollbar thumb to reflect the table's horizontal
     * scroll, and hide the whole scrollbar when the table has no horizontal overflow.
     */
    private renderStickyScrollbar(): void {
        const scrollEl = this.scrollRef?.nativeElement;
        const barEl = this.stickyScrollbarRef?.nativeElement;
        const thumbEl = this.stickyThumbRef?.nativeElement;

        if (!scrollEl || !barEl || !thumbEl) {
            return;
        }

        const { scrollWidth, clientWidth, scrollLeft } = scrollEl;
        const isOverflowing = scrollWidth > clientWidth + 1;

        this.renderer[isOverflowing ? 'removeClass' : 'addClass'](barEl, 'is-hidden');

        if (!isOverflowing) {
            return;
        }

        const trackWidth = barEl.clientWidth;
        const thumbWidth = Math.max(this.MIN_THUMB_WIDTH, (clientWidth / scrollWidth) * trackWidth);
        const contentRange = scrollWidth - clientWidth;
        const trackRange = trackWidth - thumbWidth;
        const thumbLeft = contentRange > 0 ? (scrollLeft / contentRange) * trackRange : 0;

        this.renderer.setStyle(thumbEl, 'width', `${thumbWidth}px`);
        this.renderer.setStyle(thumbEl, 'transform', `translateX(${thumbLeft}px)`);
    }


    /**
     * Start dragging the custom scrollbar thumb. Document-level listeners map horizontal
     * pointer movement onto the table's scroll position until the pointer is released.
     */
    private onThumbDragStart(event: PointerEvent): void {
        const scrollEl = this.scrollRef?.nativeElement;
        const barEl = this.stickyScrollbarRef?.nativeElement;
        const thumbEl = this.stickyThumbRef?.nativeElement;

        if (!scrollEl || !barEl || !thumbEl) {
            return;
        }

        event.preventDefault();

        const startX = event.clientX;
        const startScrollLeft = scrollEl.scrollLeft;
        const contentRange = scrollEl.scrollWidth - scrollEl.clientWidth;
        const trackRange = barEl.clientWidth - thumbEl.offsetWidth;

        this.renderer.addClass(thumbEl, 'is-dragging');

        const onMove = (moveEvent: PointerEvent) => {
            if (trackRange <= 0) {
                return;
            }

            const delta = moveEvent.clientX - startX;
            scrollEl.scrollLeft = startScrollLeft + (delta / trackRange) * contentRange;
            this.renderStickyScrollbar();
        };

        const onUp = () => {
            this.renderer.removeClass(thumbEl, 'is-dragging');
            this.dragCleanup?.();
            this.dragCleanup = undefined;
        };

        const removeMove = this.renderer.listen('document', 'pointermove', onMove);
        const removeUp = this.renderer.listen('document', 'pointerup', onUp);

        this.dragCleanup = () => {
            removeMove();
            removeUp();
        };
    }


    private buildColumnSearchForm(): void {
        this.columnSearchForm = new UntypedFormGroup(
            Object.fromEntries((this.columns || []).map(c => [c.name, new UntypedFormControl('')]))
        );
    }


    /**
     * Toggle the selection of a single row.
     * @param item presented item in this row
     * @param event checkbox change event
     */
    public toggleRowSelection(item: T, event: any): void {
        const checked = event.currentTarget.checked;

        if (checked) {
            this.selectedItems.push(item);
        } else {
            const idx = this.selectedItems.indexOf(item);

            if (idx !== -1) {
                this.selectedItems.splice(idx, 1);
            }
        }

        this.selectedChange.emit(this.selectedItems);
    }


    /**
     * Toggle the selection of all displayed elements.
     * @param event global checkbox change event
     */
    public toggleAllRowSelections(event: any): void {
        const checked = event.currentTarget.checked;

        if (checked) {
            this.selectedItems = [...this.items];
        } else {
            this.selectedItems = [];
        }

        this.selectedChange.emit(this.selectedItems);
    }


    /**
     * On hidden status change of a column.
     * @param column with changed hidden status.
     */
    public onColumnVisibilityChange(column: Column) {
        const col = this.columns.find(c => c.name === column.name);
        const colIndex = this.columns.indexOf(col);
        this.columns[colIndex].hidden = column.hidden;

        this.columnVisibilityChange.emit(column);
    }


    /**
     * Reset the columns to the initial set.
     */
    public onColumnsReset(): void {
        for (const col of this.columns) {
            col.hidden = !this.initialVisibleColumns.includes(col.name);
        }

        this.columnVisibilityChange.emit();
    }


    /**
     * On hidden change of a column search.
     */
    public onColumnSearchVisibilityChange() {
        this.columnSearchIconHidden = !this.columnSearchIconHidden;

        this.columnSearchChange.emit([]);
    }


    /**
     * Function when on sort changed emitter.
     * @param sort
     */
    public onSortChange(sort: Sort): void {
        if (this.sort.name === sort.name && this.sort.order === sort.order) {
            this.sort.order = this.sort.order === this.ASC ? this.DSC : this.ASC;
        } else {
            this.sort.name = sort.name;
            this.sort.order = sort.order;
        }

        this.sortChange.emit(this.sort);
    }


    /**
     * Page change.
     * @param page new page number
     */
    public onPageChange(page: number): void {
        this.selectedItems = [];
        this.page = page;

        this.pageChange.emit(page);
    }


    /**
     * Save table state over `TableService`.
     * @param name
     */
    public onStateSave(name: string): void {
        const columns = this.columns.filter(c => !c.hidden).map(c => c.name);

        const tableState = {
            name,
            page: this.page,
            pageSize: this.pageSize,
            sort: this.sort,
            visibleColumns: columns
        } as TableState;

        this.tableState = tableState;
        this.tableStates.push(tableState);
        this.tableService.addTableState(this.router.url, this.id, tableState);

        this.stateSave.emit(tableState);
    }


    /**
     * Update a existing state.
     * @param state
     */
    public onStateUpdate(state: TableState): void {
        const columns = this.columns.filter(c => !c.hidden).map(c => c.name);

        const tableState = {
            name: state.name,
            page: this.page,
            pageSize: this.pageSize,
            sort: this.sort,
            visibleColumns: columns
        } as TableState;

        this.tableState = tableState;
        const stateIDX = this.tableStates.indexOf(state);

        if (stateIDX > -1) {
            this.tableStates[stateIDX] = this.tableState;
        }

        this.tableService.updateTableState(this.router.url, this.id, state, this.tableState);
        this.stateUpdate.emit(tableState);
    }


    /**
     * When state was selected
     * @param state
     */
    public onStateSelect(state: TableState): void {
        this.tableState = state;
        this.tableService.setCurrentTableState(this.router.url, this.id, state);
        this.stateSelect.emit(state);
    }


    /**
     * Delete a state from the setting.
     * @param state
     */
    public onStateDelete(state: TableState): void {
        this.tableService.removeTableState(this.router.url, this.id, state);
        this.stateDelete.emit(state);
    }


    /**
     * Emit current state reset.
     */
    public onStateReset(): void {
        this.tableService.setCurrentTableState(this.router.url, this.id, undefined);
        this.stateReset.emit();
    }


    /**
     * Navigates to the specified item if object reference links are enabled and an object ID is present.
     * @param item - The item to navigate to.
     */
    navigateToItem(item: any): void {
        if (this.enableObjectReferenceLinks && item?.object_information.object_id) {
            this.router.navigate([...this.referenceViewPath, item?.object_information.object_id]);
        }
    }

    /**
     * to Computed property to determine if rows should be draggable
     */
    public get isDraggable(): boolean {
        return this.draggableEnabled && (!this.paginationEnabled || this.totalItems <= this.pageSize);
    }

    /**
    * to handle row drop event
    */
    public onRowDrop(event: CdkDragDrop<T[]>): void {
        const itemsCopy = [...this.items]; // Create a copy to avoid mutating input directly
        moveItemInArray(itemsCopy, event.previousIndex, event.currentIndex);
        this.orderChange.emit(itemsCopy); // Emit the new order to the parent
    }
}
