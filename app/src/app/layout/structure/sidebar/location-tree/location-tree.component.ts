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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/

import { Component, inject, OnInit, OnDestroy, Input, Output, EventEmitter, ChangeDetectorRef } from '@angular/core';
import { MatTreeNestedDataSource } from '@angular/material/tree';
import { Router } from '@angular/router';

import { EMPTY, ReplaySubject, BehaviorSubject, Subject, Subscription, merge } from 'rxjs';
import { catchError, debounceTime, distinctUntilChanged, map, switchMap, takeUntil } from 'rxjs/operators';

import { LocationService, LocationTreeNode, LocationTreeSearchNode } from 'src/app/framework/services/location.service';
import { ObjectService } from 'src/app/framework/services/object.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { LocationOrganizerService } from 'src/app/core/components/location-tree-organizer/location-organizer.service';
import { SidebarService } from 'src/app/layout/services/sidebar.service';

/* -------------------------------------------------------------------------- */
/*                                 INTERFACES                                 */
/* -------------------------------------------------------------------------- */

interface LocationNode {
    public_id: number;
    name: string;
    icon: string;
    parent: number;
    object_id: number;
    has_children: boolean;
    children$: BehaviorSubject<LocationNode[]>;
    loaded: boolean;
    loading: boolean;
    /** Expansion state of the node — bound to the tree via `isExpanded`. */
    expanded: boolean;
}

/* -------------------------------------------------------------------------- */

@Component({
    selector: 'location-tree',
    templateUrl: './location-tree.component.html',
    styleUrls: ['./location-tree.component.scss'],
    standalone: false
})
export class LocationTreeComponent implements OnInit, OnDestroy {

    private static readonly SEARCH_DEBOUNCE_MS = 300;
    /**
     * One save writes more than once - the object, then its active state - and each write announces
     * itself, so the reloads are collapsed into the last one instead of reloading the tree per write.
     */
    private static readonly REFRESH_DEBOUNCE_MS = 200;
    private static readonly ROOTS_ERROR = "We couldn't load the locations. Please try again.";
    private static readonly SEARCH_ERROR = "We couldn't complete the location search. Please try again.";
    private static readonly CHILDREN_ERROR = "We couldn't load the child locations. Please try again.";

    private unsubscribe: ReplaySubject<void> = new ReplaySubject<void>();

    objectServiceSubscription: Subscription;
    locationServiceSubscription: Subscription;

    childrenAccessor = (node: LocationNode) => node.children$;
    dataSource = new MatTreeNestedDataSource<LocationNode>();

    /**
     * Input for sidebar expansion state
     */
    @Input() isExpanded: boolean;
    @Input() showSidebarExpandButton: boolean = true;

    /**
     * Output event for expand button click
     */
    @Output() expandClicked = new EventEmitter<void>();

    /**
     * used for highlighting the selected location
     */
    public selectedLocationID: number;
    private _searchString: string = '';

    /** Browse mode has at least one root location */
    public hasLocations: boolean = false;
    /** The active search returned at least one match */
    public hasSearchResults: boolean = true;
    /** The tree is showing search results rather than the browse tree */
    public inSearchMode: boolean = false;
    /** A search request is in flight */
    public isSearching: boolean = false;
    /** Message shown in the location section when a load/search fails */
    public errorMessage: string | null = null;

    /**
     * public_ids of the nodes expanded while browsing. Kept so the browse tree can restore its
     * shape after a reload (object/location change) or after leaving search, without re-fetching
     * the whole forest.
     */
    private readonly expandedIds = new Set<number>();

    /** Raw search-box keystrokes */
    private readonly searchInput$ = new Subject<string>();
    /** Re-runs the current view (browse or search) after a data change */
    private readonly refresh$ = new Subject<void>();

    private readonly locationService = inject(LocationService);
    private readonly objectService = inject(ObjectService);
    private readonly toast = inject(ToastService);
    private readonly route = inject(Router);
    private readonly cdRef = inject(ChangeDetectorRef);
    private readonly locationOrganizer = inject(LocationOrganizerService);
    private readonly sidebarService = inject(SidebarService);

    /* -------------------------------------------------------------------------- */
    /*                                LIFE - CYCLE                                */
    /* -------------------------------------------------------------------------- */

    public ngOnInit() {
        this.objectServiceSubscription = this.objectService.objectActionSource.subscribe(
            (action: string) => this.onObjectActionEventRecieved(action)
        );

        this.locationServiceSubscription = this.locationService.locationActionSource.subscribe(
            (action: string) => this.onLocationActionEventRecieved(action)
        );

        // The tree is a section of the sidebar, so it reloads on the same signal the rest of it does.
        this.sidebarService.reloaded.pipe(takeUntil(this.unsubscribe)).subscribe(() => this.refresh$.next());

        this.listenForSearch();
        this.loadRoots();
    }

    public ngOnDestroy(): void {
        this.objectServiceSubscription?.unsubscribe();
        this.locationServiceSubscription?.unsubscribe();
        this.unsubscribe.next();
        this.unsubscribe.complete();
    }

    /* -------------------------------------------------------------------------- */
    /*                                   SEARCH                                   */
    /* -------------------------------------------------------------------------- */

    /**
     * Getter for search string
     */
    get searchString(): string {
        return this._searchString;
    }

    /**
     * Setter for the search string. Feeds the debounced search pipeline.
     */
    set searchString(value: string) {
        this._searchString = value;
        this.searchInput$.next(value);
    }

    /**
     * Reset the search string, returning to the browse tree.
     */
    handleSearchReset() {
        this.searchString = "";
    }

    /* -------------------------------------------------------------------------- */
    /*                               TREE FUNCTIONS                               */
    /* -------------------------------------------------------------------------- */

    /**
    * Set the selected location and loads the object overview in the content view
    *
    * @param clickedObjectID the objectID of the location which is clicked in location tree
    */
    public onLocationElementClicked(clickedObjectID: number) {
        this.selectedLocationID = clickedObjectID;
        this.route.navigateByUrl('/framework/object/view/' + clickedObjectID);
    }

    /**
     * Expands or collapses a node. While browsing, children are fetched on first expand and cached
     * on the node; while searching every node is already loaded, so this never triggers a request.
     *
     * @param node the node to toggle
     */
    public toggleNode(node: LocationNode): void {
        if (node.expanded) {
            node.expanded = false;
            this.expandedIds.delete(node.public_id);
            return;
        }

        if (node.has_children && !node.loaded) {
            this.loadChildren(node);
            return;
        }

        this.expandNode(node);
    }


    /**
     * Mirrors the tree's expansion state back onto the node, so branches opened with the keyboard
     * (ArrowLeft/ArrowRight) stay in sync with the chevron and the browse-restore memory.
     *
     * @param node the node whose expansion changed
     * @param expanded the new expansion state
     */
    public onExpandedChange(node: LocationNode, expanded: boolean): void {
        node.expanded = expanded;

        // Search results are opened wholesale, so they must not overwrite the browse-restore memory.
        if (!this.inSearchMode) {
            expanded ? this.expandedIds.add(node.public_id) : this.expandedIds.delete(node.public_id);
        }

        if (expanded && node.has_children && !node.loaded && !node.loading) {
            this.loadChildren(node);
            return;
        }

        if (expanded) {
            // The branch opened over children that were already fetched, so the tree flattened itself
            // before the expansion landed. Refresh the keyboard order now that both are in place.
            this.republishTree();
        }
    }

    /**
     * Emits expand event to parent component
     */
    public onSidebarExpandClicked() {
        this.expandClicked.emit();
    }

    /**
     * Opens the location organizer modal for re-parenting locations via drag-and-drop. Moves made
     * inside the modal emit a location action, which the subscription in ngOnInit turns into a tree
     * refresh, so no explicit reload is needed here.
     */
    public openOrganizer(): void {
        this.locationOrganizer.open();
    }

    /**
    * Whether a node should render an expand control. Uses the has_children flag so the control
    * appears before the children are loaded.
    */
    hasChild = (_: number, node: LocationNode) => node.has_children;

    /**
     * EventListener function which reloads the tree when objects were changed
     *
     * @param action (string): Type of object action (create, delete or update)
     */
    public onObjectActionEventRecieved(action: string) {
        this.refresh$.next();
    }

    /**
     * EventListener function which reloads the tree when locations were changed
     *
     * @param action (string): Type of location action (create, delete or update)
     */
    public onLocationActionEventRecieved(action: string) {
        this.refresh$.next();
    }

    /**
     * Reloads the current view (browse or search)
     */
    public reloadTree() {
        this.refresh$.next();
    }

    /* -------------------------------------------------------------------------- */
    /*                             HELPER - FUNCTIONS                             */
    /* -------------------------------------------------------------------------- */

    private listenForSearch(): void {
        const typedTerm$ = this.searchInput$.pipe(
            debounceTime(LocationTreeComponent.SEARCH_DEBOUNCE_MS),
            map((term) => term.trim()),
            distinctUntilChanged()
        );

        const refreshedTerm$ = this.refresh$.pipe(
            debounceTime(LocationTreeComponent.REFRESH_DEBOUNCE_MS),
            map(() => this._searchString.trim())
        );

        merge(typedTerm$, refreshedTerm$)
            .pipe(
                switchMap((term) => {
                    if (!term) {
                        this.exitSearchMode();
                        return EMPTY;
                    }

                    this.beginSearch();

                    return this.locationService.searchTree(term).pipe(
                        catchError(() => {
                            this.showLoadError(LocationTreeComponent.SEARCH_ERROR);
                            return EMPTY;
                        })
                    );
                }),
                takeUntil(this.unsubscribe)
            )
            .subscribe((results: LocationTreeSearchNode[]) => this.applySearchResults(results));
    }

    /**
     * Loads the first level of the browse tree and restores any previously expanded branches.
     */
    private loadRoots(): void {
        this.locationService.getTreeRoots().pipe(takeUntil(this.unsubscribe))
            .subscribe({
                next: (roots: LocationTreeNode[]) => {
                    const nodes = roots.map((root) => this.toBrowseNode(root));
                    this.errorMessage = null;
                    this.inSearchMode = false;
                    this.hasLocations = nodes.length > 0;
                    this.dataSource.data = nodes;
                    this.restoreExpansion(nodes);
                    this.cdRef.markForCheck();
                },
                error: () => this.showLoadError(LocationTreeComponent.ROOTS_ERROR)
            });
    }

    /**
     * Fetches the direct children of a node, publishes them to the tree, then expands it.
     *
     * @param node the node whose children should be loaded
     */
    private loadChildren(node: LocationNode): void {
        node.loading = true;

        this.locationService.getTreeChildren(node.public_id).pipe(takeUntil(this.unsubscribe))
            .subscribe({
                next: (children: LocationTreeNode[]) => {
                    node.children$.next(children.map((child) => this.toBrowseNode(child)));
                    node.loaded = true;
                    node.loading = false;
                    this.expandNode(node);
                    this.republishTree();
                },
                error: () => {
                    node.loading = false;
                    this.toast.error(LocationTreeComponent.CHILDREN_ERROR);
                    this.cdRef.markForCheck();
                }
            });
    }

    /**
     * Marks a search as started, clearing any previous error and blanking the tree while the
     * request is in flight.
     */
    private beginSearch(): void {
        this.inSearchMode = true;
        this.isSearching = true;
        this.errorMessage = null;
        this.cdRef.markForCheck();
    }

    /**
     * Renders a search result: the backend already returns the matching subtrees fully materialised,
     * so the nodes are mapped and expanded in place with no further requests.
     *
     * @param results the matching subtrees returned by the search endpoint
     */
    private applySearchResults(results: LocationTreeSearchNode[]): void {
        const nodes = results.map((result) => this.toSearchNode(result));
        this.isSearching = false;
        this.hasSearchResults = nodes.length > 0;
        this.expandAll(nodes);
        this.dataSource.data = nodes;
        this.cdRef.markForCheck();
    }

    /**
     * Leaves search mode and reloads the browse tree.
     */
    private exitSearchMode(): void {
        this.inSearchMode = false;
        this.isSearching = false;
        this.loadRoots();
    }

    /**
     * Re-fetches and re-expands the branches that were open before a browse reload.
     *
     * @param nodes the freshly loaded nodes of the current level
     */
    private restoreExpansion(nodes: LocationNode[]): void {
        if (!this.expandedIds.size) {
            return;
        }

        for (const node of nodes) {
            if (!node.has_children || !this.expandedIds.has(node.public_id)) {
                continue;
            }

            this.locationService.getTreeChildren(node.public_id).pipe(takeUntil(this.unsubscribe))
                .subscribe((children: LocationTreeNode[]) => {
                    const childNodes = children.map((child) => this.toBrowseNode(child));
                    node.children$.next(childNodes);
                    node.loaded = true;
                    node.expanded = true;
                    this.restoreExpansion(childNodes);
                    this.republishTree();
                    this.cdRef.markForCheck();
                });
        }
    }

    /**
     * Expands a node and remembers it so its state survives a browse reload.
     *
     * @param node the node to expand
     */
    private expandNode(node: LocationNode): void {
        node.expanded = true;
        this.expandedIds.add(node.public_id);
        this.cdRef.markForCheck();
    }

    /**
     * Expands every node that has children (used to fully open a search result).
     *
     * @param nodes the nodes to expand recursively
     */
    private expandAll(nodes: LocationNode[]): void {
        for (const node of nodes) {
            if (node.has_children) {
                node.expanded = true;
                this.expandAll(node.children$.value);
            }
        }
    }

    /**
     * Re-emits the current level so the tree rebuilds its flattened node cache. That cache — which is
     * what arrow-key navigation walks — is a snapshot taken when a branch opens, so without this the
     * children that arrive afterwards are skipped. The nodes keep their identity, so nothing re-renders.
     */
    private republishTree(): void {
        // Deferred: the tree re-flattens several times while a branch opens, and an inline re-emit
        // races those runs and loses. A microtask lands after the burst, on settled state.
        Promise.resolve().then(() => {
            this.dataSource.data = [...this.dataSource.data];
        });
    }

    /**
     * Shows an error message in the location section.
     *
     * @param message the user-facing message
     */
    private showLoadError(message: string): void {
        this.isSearching = false;
        this.errorMessage = message;
        this.cdRef.markForCheck();
    }

    /**
     * Maps a lazy (browse) backend node to the view model. Children are loaded on demand.
     *
     * @param raw the node returned by the lazy tree endpoints
     */
    private toBrowseNode(raw: LocationTreeNode): LocationNode {
        return {
            public_id: raw.public_id,
            name: raw.name,
            icon: raw.type_icon,
            parent: raw.parent,
            object_id: raw.object_id,
            has_children: raw.has_children,
            children$: new BehaviorSubject<LocationNode[]>([]),
            loaded: !raw.has_children,
            loading: false,
            expanded: false
        };
    }

    /**
     * Maps a search backend node (with its subtree embedded) to the view model. All descendants are
     * already present, so the node is flagged as loaded.
     *
     * @param raw the node returned by the search endpoint
     */
    private toSearchNode(raw: LocationTreeSearchNode): LocationNode {
        const children = (raw.children ?? []).map((child) => this.toSearchNode(child));

        return {
            public_id: raw.public_id,
            name: raw.name,
            icon: raw.icon,
            parent: raw.parent,
            object_id: raw.object_id,
            has_children: children.length > 0,
            children$: new BehaviorSubject<LocationNode[]>(children),
            loaded: true,
            loading: false,
            expanded: false
        };
    }
}
