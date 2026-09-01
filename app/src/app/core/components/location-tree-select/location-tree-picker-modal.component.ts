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
import { Component, ElementRef, inject, Input, OnDestroy, OnInit, ViewChild } from '@angular/core';
import { MatTreeNestedDataSource } from '@angular/material/tree';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';

import { BehaviorSubject, EMPTY, ReplaySubject, Subject } from 'rxjs';
import { catchError, debounceTime, distinctUntilChanged, map, switchMap, takeUntil } from 'rxjs/operators';

import { LocationService, LocationTreeNode, LocationTreePathNode, LocationTreeSearchNode } from 'src/app/framework/services/location.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { LocationTreeSelectNode, ROOT_LOCATION } from './location-tree-select.model';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'app-location-tree-picker-modal',
    templateUrl: './location-tree-picker-modal.component.html',
    styleUrls: ['./location-tree-picker-modal.component.scss'],
    standalone: false
})
export class LocationTreePickerModalComponent implements OnInit, OnDestroy {

    private static readonly SEARCH_DEBOUNCE_MS = 300;
    private static readonly ROOTS_ERROR = "We couldn't load the locations. Please try again.";
    private static readonly SEARCH_ERROR = "We couldn't complete the location search. Please try again.";
    private static readonly CHILDREN_ERROR = "We couldn't load the child locations. Please try again.";

    public readonly nonSelectableHint = 'This type cannot be selected as a parent location';
    public readonly root = ROOT_LOCATION;

    /** public_id of the currently selected location (highlighted when visible). */
    @Input() public selectedId: number | null = null;

    /** public_id of the edited object; its own node and descendants are shown but not selectable. */
    @Input() public excludeObjectId: number | null = null;

    @Input() public title = 'Select a location';

    public readonly childrenAccessor = (node: LocationTreeSelectNode) => node.children$;
    public readonly dataSource = new MatTreeNestedDataSource<LocationTreeSelectNode>();

    public hasLocations = false;
    public hasSearchResults = true;
    public inSearchMode = false;
    public isSearching = false;
    public isLoadingRoots = false;
    public errorMessage: string | null = null;

    private _searchString = '';
    private scrollTimer: ReturnType<typeof setTimeout> | null = null;
    private readonly searchInput$ = new Subject<string>();
    private readonly unsubscribe = new ReplaySubject<void>(1);

    public readonly activeModal = inject(NgbActiveModal);
    private readonly locationService = inject(LocationService);
    private readonly toast = inject(ToastService);

    @ViewChild('treeContainer') private treeContainer?: ElementRef<HTMLElement>;

    /* --------------------------------------------------- LIFE CYCLE -------------------------------------------------- */

    public ngOnInit(): void {
        this.listenForSearch();
        this.loadInitialTree();
    }

    public ngOnDestroy(): void {
        if (this.scrollTimer !== null) {
            clearTimeout(this.scrollTimer);
        }

        this.unsubscribe.next();
        this.unsubscribe.complete();
    }

    /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    public get searchString(): string {
        return this._searchString;
    }

    public set searchString(value: string) {
        this._searchString = value;
        this.searchInput$.next(value);
    }

    public handleSearchReset(): void {
        this.searchString = '';
    }

    public toggleNode(node: LocationTreeSelectNode): void {
        node.expanded = !node.expanded;

        if (node.expanded) {
            this.loadChildrenIfNeeded(node);
        }
    }

    /**
     * Mirrors the tree's expansion state back onto the node so pointer and keyboard (ArrowLeft/Right)
     * stay in sync, and fetches the children the first time a branch opens.
     */
    public onExpandedChange(node: LocationTreeSelectNode, expanded: boolean): void {
        node.expanded = expanded;

        if (expanded) {
            this.loadChildrenIfNeeded(node);
        }
    }

    /** Selecting a valid node closes the modal with the picked location. */
    public selectNode(node: LocationTreeSelectNode): void {
        if (!node.selectable || node.excluded) {
            return;
        }

        this.activeModal.close({
            public_id: node.public_id,
            object_id: node.object_id,
            name: node.name,
            icon: node.icon
        });
    }

    /** Places the object at the top level (parent = root). */
    public selectRoot(): void {
        this.activeModal.close({
            public_id: this.root.public_id,
            object_id: 0,
            name: this.root.name,
            icon: this.root.icon
        });
    }

    /** ArrowDown from the search box hands focus to the first tree node (CDK then owns navigation). */
    public onSearchKeydown(event: KeyboardEvent): void {
        if (event.key !== 'ArrowDown') {
            return;
        }

        const firstNode = this.treeContainer?.nativeElement.querySelector<HTMLElement>('[role="treeitem"]');
        if (firstNode) {
            event.preventDefault();
            firstNode.focus();
        }
    }

    public hasChild = (_: number, node: LocationTreeSelectNode): boolean => node.has_children;

    /* ------------------------------------------------ PRIVATE FUNCTIONS ---------------------------------------------- */

    private listenForSearch(): void {
        this.searchInput$.pipe(
            debounceTime(LocationTreePickerModalComponent.SEARCH_DEBOUNCE_MS),
            map((term) => term.trim()),
            distinctUntilChanged(),
            switchMap((term) => {
                if (!term) {
                    this.exitSearchMode();
                    return EMPTY;
                }

                this.beginSearch();

                return this.locationService.searchTree(term).pipe(
                    catchError(() => {
                        this.showRootsError(LocationTreePickerModalComponent.SEARCH_ERROR);
                        return EMPTY;
                    })
                );
            }),
            takeUntil(this.unsubscribe)
        ).subscribe((results: LocationTreeSearchNode[]) => this.applySearchResults(results));
    }

    /** Reveals the pre-selected location's full path when one is set, otherwise shows the root level. */
    private loadInitialTree(): void {
        if (this.selectedId != null && this.selectedId !== this.root.public_id) {
            this.loadPath(this.selectedId);
            return;
        }

        this.loadRoots();
    }

    /**
     * Loads the tree already expanded down to the selected location so a deeply nested selection is
     * visible immediately. Falls back to the plain root list if the path lookup fails.
     */
    private loadPath(publicID: number): void {
        this.isLoadingRoots = true;
        this.errorMessage = null;

        this.locationService.getTreePath(publicID).pipe(takeUntil(this.unsubscribe)).subscribe({
            next: (roots: LocationTreePathNode[]) => {
                const nodes = roots.map((root) => this.toPathNode(root, false));
                this.isLoadingRoots = false;
                this.inSearchMode = false;
                this.hasLocations = nodes.length > 0;
                this.expandPath(nodes);
                this.dataSource.data = nodes;
                this.scrollSelectedIntoView();
            },
            error: () => this.loadRoots()
        });
    }

    private loadRoots(): void {
        this.isLoadingRoots = true;
        this.errorMessage = null;

        this.locationService.getTreeRoots().pipe(takeUntil(this.unsubscribe)).subscribe({
            next: (roots: LocationTreeNode[]) => {
                const nodes = roots.map((root) => this.toBrowseNode(root, false));
                this.isLoadingRoots = false;
                this.inSearchMode = false;
                this.hasLocations = nodes.length > 0;
                this.dataSource.data = nodes;
            },
            error: () => this.showRootsError(LocationTreePickerModalComponent.ROOTS_ERROR)
        });
    }

    /** Fetches a branch's children the first time it opens; a no-op for loaded or in-flight nodes. */
    private loadChildrenIfNeeded(node: LocationTreeSelectNode): void {
        if (node.has_children && !node.loaded && !node.loading) {
            this.loadChildren(node);
        }
    }

    private loadChildren(node: LocationTreeSelectNode): void {
        node.loading = true;

        this.locationService.getTreeChildren(node.public_id).pipe(takeUntil(this.unsubscribe)).subscribe({
            next: (children: LocationTreeNode[]) => {
                node.children$.next(children.map((child) => this.toBrowseNode(child, node.excluded)));
                node.loaded = true;
                node.loading = false;
            },
            error: () => {
                node.loading = false;
                node.expanded = false;
                this.toast.error(LocationTreePickerModalComponent.CHILDREN_ERROR);
            }
        });
    }

    private beginSearch(): void {
        this.inSearchMode = true;
        this.isSearching = true;
        this.errorMessage = null;
    }

    private applySearchResults(results: LocationTreeSearchNode[]): void {
        const nodes = results.map((result) => this.toSearchNode(result, false));
        this.isSearching = false;
        this.hasSearchResults = nodes.length > 0;
        this.expandAll(nodes);
        this.dataSource.data = nodes;
    }

    private exitSearchMode(): void {
        this.inSearchMode = false;
        this.isSearching = false;
        this.loadInitialTree();
    }

    private showRootsError(message: string): void {
        this.isSearching = false;
        this.isLoadingRoots = false;
        this.errorMessage = message;
    }

    private toBrowseNode(raw: LocationTreeNode, parentExcluded: boolean): LocationTreeSelectNode {
        return {
            public_id: raw.public_id,
            name: raw.name,
            icon: raw.type_icon,
            parent: raw.parent,
            object_id: raw.object_id,
            has_children: raw.has_children,
            selectable: raw.type_selectable !== false,
            excluded: parentExcluded || this.isSelf(raw.object_id),
            children$: new BehaviorSubject<LocationTreeSelectNode[]>([]),
            loaded: !raw.has_children,
            loading: false,
            expanded: false
        };
    }

    private toPathNode(raw: LocationTreePathNode, parentExcluded: boolean): LocationTreeSelectNode {
        const excluded = parentExcluded || this.isSelf(raw.object_id);
        const hasInlineChildren = Array.isArray(raw.children);
        const children = raw.children?.map((child) => this.toPathNode(child, excluded)) ?? [];

        return {
            public_id: raw.public_id,
            name: raw.name,
            icon: raw.type_icon,
            parent: raw.parent,
            object_id: raw.object_id,
            has_children: raw.has_children,
            selectable: raw.type_selectable !== false,
            excluded,
            children$: new BehaviorSubject<LocationTreeSelectNode[]>(children),
            loaded: hasInlineChildren || !raw.has_children,
            loading: false,
            expanded: false
        };
    }

    private toSearchNode(raw: LocationTreeSearchNode, parentExcluded: boolean): LocationTreeSelectNode {
        const excluded = parentExcluded || this.isSelf(raw.object_id);
        const children = (raw.children ?? []).map((child) => this.toSearchNode(child, excluded));

        return {
            public_id: raw.public_id,
            name: raw.name,
            icon: raw.icon,
            parent: raw.parent,
            object_id: raw.object_id,
            has_children: children.length > 0,
            selectable: raw.type_selectable !== false,
            excluded,
            children$: new BehaviorSubject<LocationTreeSelectNode[]>(children),
            loaded: true,
            loading: false,
            expanded: false
        };
    }

    private expandAll(nodes: LocationTreeSelectNode[]): void {
        for (const node of nodes) {
            if (node.has_children) {
                node.expanded = true;
                this.expandAll(node.children$.value);
            }
        }
    }

    /** Expands only the nodes whose children arrived inline — the ancestor chain of the selection. */
    private expandPath(nodes: LocationTreeSelectNode[]): void {
        for (const node of nodes) {
            if (node.loaded && node.children$.value.length > 0) {
                node.expanded = true;
                this.expandPath(node.children$.value);
            }
        }
    }

    /** Brings the highlighted node into view once the expanded path has rendered. */
    private scrollSelectedIntoView(): void {
        if (this.selectedId == null) {
            return;
        }

        this.scrollTimer = setTimeout(() => {
            const selected = this.treeContainer?.nativeElement
                .querySelector<HTMLElement>('.ltp-node.is-selected');
            selected?.scrollIntoView({ block: 'center' });
        });
    }

    private isSelf(objectId: number): boolean {
        return this.excludeObjectId != null && objectId === this.excludeObjectId;
    }
}
