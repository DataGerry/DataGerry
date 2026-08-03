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
import { Component, inject, OnDestroy, OnInit } from '@angular/core';
import { NestedTreeControl } from '@angular/cdk/tree';
import { MatTreeNestedDataSource } from '@angular/material/tree';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';

import { BehaviorSubject, EMPTY, merge, Observable, ReplaySubject, Subject } from 'rxjs';
import { catchError, debounceTime, distinctUntilChanged, finalize, map, switchMap, takeUntil } from 'rxjs/operators';

import { LocationService, LocationTreeNode, LocationTreeSearchNode } from 'src/app/framework/services/location.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { PermissionService } from 'src/app/modules/auth/services/permission.service';
import { LocationTreeSelectNode, ROOT_LOCATION } from '../location-tree-select/location-tree-select.model';
import { DropCheck, evaluateDrop } from './location-move-rules';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'app-location-tree-organizer-modal',
    templateUrl: './location-tree-organizer-modal.component.html',
    styleUrls: ['./location-tree-organizer-modal.component.scss'],
    standalone: false
})
export class LocationTreeOrganizerModalComponent implements OnInit, OnDestroy {

    private static readonly SEARCH_DEBOUNCE_MS = 300;
    private static readonly ROOTS_ERROR = "We couldn't load the locations. Please try again.";
    private static readonly SEARCH_ERROR = "We couldn't complete the location search. Please try again.";
    private static readonly CHILDREN_ERROR = "We couldn't load the child locations. Please try again.";
    private static readonly MOVE_ERROR = "We couldn't move the selected location(s). Please try again.";
    private static readonly MOVE_SUCCESS = 'Location hierarchy updated';
    private static readonly EDIT_RIGHT = 'base.framework.location.edit';

    /** Whether the current user may re-parent locations. Gates the drag/drop and "Move here" affordances. */
    public canEdit = false;

    public readonly root = ROOT_LOCATION;
    public readonly nonSelectableHint = 'This type cannot hold child locations';

    public readonly treeControl = new NestedTreeControl<LocationTreeSelectNode>((node) => node.children$);
    public readonly dataSource = new MatTreeNestedDataSource<LocationTreeSelectNode>();

    public hasLocations = false;
    public hasSearchResults = true;
    public inSearchMode = false;
    public isSearching = false;
    public isLoadingRoots = false;
    public isProcessing = false;
    public errorMessage: string | null = null;

    /** public_ids ticked for a batch move. */
    public readonly selected = new Set<number>();

    /** Row currently hovered as a drop target, plus whether the drop is allowed and (if not) why. */
    public dropTargetId: number | null = null;
    public dropTargetValid = false;
    public dropHint: string | null = null;
    public dropHintX = 0;
    public dropHintY = 0;

    private _searchString = '';

    /** public_ids being dragged in the current gesture. */
    private readonly draggedIds = new Set<number>();
    /** Every node in the current view, keyed by public_id — used for ancestor walks and id resolution. */
    private readonly nodesById = new Map<number, LocationTreeSelectNode>();

    private readonly searchInput$ = new Subject<string>();
    /** Re-runs the current search term after a move, bypassing distinctUntilChanged. */
    private readonly refreshSearch$ = new Subject<void>();
    private readonly unsubscribe = new ReplaySubject<void>(1);

    public readonly activeModal = inject(NgbActiveModal);
    private readonly locationService = inject(LocationService);
    private readonly toast = inject(ToastService);
    private readonly permission = inject(PermissionService);

    /* --------------------------------------------------- LIFE CYCLE -------------------------------------------------- */

    public ngOnInit(): void {
        this.canEdit = this.permission.hasRight(LocationTreeOrganizerModalComponent.EDIT_RIGHT)
            || this.permission.hasExtendedRight(LocationTreeOrganizerModalComponent.EDIT_RIGHT);
        this.listenForSearch();
        this.listenForExpansion();
        this.loadRoots();
    }

    public ngOnDestroy(): void {
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
        this.treeControl.toggle(node);
    }

    public isSelected(node: LocationTreeSelectNode): boolean {
        return this.selected.has(node.public_id);
    }

    public toggleSelect(node: LocationTreeSelectNode): void {
        this.selected.has(node.public_id)
            ? this.selected.delete(node.public_id)
            : this.selected.add(node.public_id);
    }

    public clearSelection(): void {
        this.selected.clear();
    }

    /** Whether the ticked selection may be moved under a target (drives the "Move here" affordance). */
    public canMoveSelectionTo(targetId: number): boolean {
        return this.selected.size > 0 && this.checkDrop(targetId, this.selected).ok;
    }

    /* ------------------------------------------------- DRAG & DROP --------------------------------------------------- */

    public onDragStart(event: DragEvent, node: LocationTreeSelectNode): void {
        this.draggedIds.clear();

        if (this.selected.has(node.public_id) && this.selected.size > 1) {
            this.selected.forEach((id) => this.draggedIds.add(id));
        } else {
            this.draggedIds.add(node.public_id);
        }

        if (event.dataTransfer) {
            event.dataTransfer.effectAllowed = 'move';
            // Firefox requires payload data for a drag to start.
            event.dataTransfer.setData('text/plain', String(node.public_id));
        }
    }

    public onDragEnd(): void {
        this.draggedIds.clear();
        this.clearDropTarget();
    }

    public onDragOver(event: DragEvent, targetId: number): void {
        const check = this.checkDrop(targetId, this.draggedIds);
        this.dropTargetId = targetId;
        this.dropTargetValid = check.ok;

        if (check.ok) {
            this.dropHint = null;
            event.preventDefault(); // only preventDefault allows the drop
            if (event.dataTransfer) {
                event.dataTransfer.dropEffect = 'move';
            }
            return;
        }

        // Invalid target: surface why, tracking the cursor like a SaaS drag tooltip.
        this.dropHint = check.reason;
        this.dropHintX = event.clientX;
        this.dropHintY = event.clientY;
    }

    public onDragLeave(targetId: number): void {
        if (this.dropTargetId === targetId) {
            this.clearDropTarget();
        }
    }

    public onDrop(event: DragEvent, targetId: number): void {
        event.preventDefault();

        if (this.checkDrop(targetId, this.draggedIds).ok) {
            this.performMove(this.draggedIds, targetId);
        }

        this.onDragEnd();
    }

    /** Keyboard/pointer alternative to dragging: move the ticked rows under the given target. */
    public moveSelectionTo(targetId: number): void {
        if (this.checkDrop(targetId, this.selected).ok) {
            this.performMove(this.selected, targetId);
        }
    }

    public hasChild = (_: number, node: LocationTreeSelectNode): boolean => node.has_children;

    /* --------------------------------------------- TREE LOADING & SEARCH --------------------------------------------- */

    private listenForSearch(): void {
        const typedTerm$ = this.searchInput$.pipe(
            debounceTime(LocationTreeOrganizerModalComponent.SEARCH_DEBOUNCE_MS),
            map((term) => term.trim()),
            distinctUntilChanged()
        );

        // refreshSearch$ re-emits the current term after a move so the same query can re-run, which
        // distinctUntilChanged would otherwise suppress.
        merge(typedTerm$, this.refreshSearch$.pipe(map(() => this._searchString.trim())))
            .pipe(
                switchMap((term) => {
                    if (!term) {
                        this.exitSearchMode();
                        return EMPTY;
                    }

                    this.beginSearch();

                    return this.locationService.searchTree(term).pipe(
                        catchError(() => {
                            this.showError(LocationTreeOrganizerModalComponent.SEARCH_ERROR);
                            return EMPTY;
                        })
                    );
                }),
                takeUntil(this.unsubscribe)
            )
            .subscribe((results: LocationTreeSearchNode[]) => this.applySearchResults(results));
    }

    /** Fetches a node's children the first time it is expanded. */
    private listenForExpansion(): void {
        this.treeControl.expansionModel.changed.pipe(takeUntil(this.unsubscribe)).subscribe((change) => {
            for (const node of change.added) {
                if (node.has_children && !node.loaded && !node.loading) {
                    this.loadChildren(node);
                }
            }
        });
    }

    private loadRoots(): void {
        this.isLoadingRoots = true;
        this.errorMessage = null;
        this.resetIndex();

        this.locationService.getTreeRoots().pipe(takeUntil(this.unsubscribe)).subscribe({
            next: (roots: LocationTreeNode[]) => {
                const nodes = roots.map((raw) => this.toBrowseNode(raw));
                this.isLoadingRoots = false;
                this.inSearchMode = false;
                this.hasLocations = nodes.length > 0;
                this.dataSource.data = nodes;
            },
            error: () => this.showError(LocationTreeOrganizerModalComponent.ROOTS_ERROR)
        });
    }

    private loadChildren(node: LocationTreeSelectNode): void {
        node.loading = true;

        this.locationService.getTreeChildren(node.public_id).pipe(takeUntil(this.unsubscribe)).subscribe({
            next: (children: LocationTreeNode[]) => {
                node.children$.next(children.map((child) => this.toBrowseNode(child)));
                node.loaded = true;
                node.loading = false;
            },
            error: () => {
                node.loading = false;
                this.treeControl.collapse(node);
                this.toast.error(LocationTreeOrganizerModalComponent.CHILDREN_ERROR);
            }
        });
    }

    private beginSearch(): void {
        this.inSearchMode = true;
        this.isSearching = true;
        this.errorMessage = null;
    }

    private applySearchResults(results: LocationTreeSearchNode[]): void {
        this.resetIndex();
        const nodes = results.map((result) => this.toSearchNode(result));
        this.isSearching = false;
        this.hasSearchResults = nodes.length > 0;
        this.dataSource.data = nodes;
        this.expandAll(nodes);
    }

    private exitSearchMode(): void {
        this.inSearchMode = false;
        this.isSearching = false;
        this.loadRoots();
    }

    private showError(message: string): void {
        this.isSearching = false;
        this.isLoadingRoots = false;
        this.errorMessage = message;
    }

    /* ------------------------------------------------- MOVING NODES -------------------------------------------------- */

    /**
     * Runs the move (single or batch). On success the browse tree is updated in place — moved nodes are
     * detached from their old parent and re-attached under the target — so only the two affected
     * branches change (no reload, no request storm, scroll preserved). In search mode the query is
     * simply re-run.
     */
    private performMove(ids: Set<number>, targetId: number): void {
        if (!this.canEdit) {
            return;
        }

        const movedNodes = [...ids]
            .map((id) => this.nodesById.get(id))
            .filter((node): node is LocationTreeSelectNode => !!node);

        if (movedNodes.length === 0) {
            return;
        }

        const objectIds = movedNodes.map((node) => node.object_id);
        this.isProcessing = true;

        const request$: Observable<unknown> = objectIds.length === 1
            ? this.locationService.moveLocation(objectIds[0], targetId)
            : this.locationService.moveLocations(objectIds, targetId);

        request$.pipe(
            finalize(() => { this.isProcessing = false; }),
            takeUntil(this.unsubscribe)
        ).subscribe({
            next: () => {
                this.toast.success(LocationTreeOrganizerModalComponent.MOVE_SUCCESS);
                this.locationService.executedAction('update');
                this.selected.clear();

                if (this.inSearchMode && this._searchString.trim()) {
                    this.refreshSearch$.next();
                } else {
                    this.applyLocalMove(movedNodes, targetId);
                }
            },
            error: (err) => {
                const message = err?.error?.message ?? LocationTreeOrganizerModalComponent.MOVE_ERROR;
                this.toast.error(message);
            }
        });
    }

    /** Detaches the moved nodes from their old parents and re-attaches them under the target. */
    private applyLocalMove(movedNodes: LocationTreeSelectNode[], targetId: number): void {
        const moved = new Set(movedNodes);

        for (const parentId of new Set(movedNodes.map((node) => node.parent))) {
            this.detachChildren(parentId, moved);
        }

        for (const node of movedNodes) {
            node.parent = targetId;
        }

        this.attachChildren(targetId, movedNodes);
        this.refreshTreeRendering();
    }

    /** Removes the given nodes from a parent's child list (or the root level), collapsing it if empty. */
    private detachChildren(parentId: number, moved: Set<LocationTreeSelectNode>): void {
        if (parentId === this.root.public_id) {
            this.dataSource.data = this.dataSource.data.filter((node) => !moved.has(node));
            return;
        }

        const parent = this.nodesById.get(parentId);
        if (!parent) {
            return;
        }

        const remaining = parent.children$.value.filter((node) => !moved.has(node));
        parent.children$.next(remaining);

        if (remaining.length === 0) {
            parent.has_children = false;
            parent.loaded = true;
            this.treeControl.collapse(parent);
        }
    }

    /** Adds the moved nodes under the target (root level or a node) and reveals the branch. */
    private attachChildren(targetId: number, movedNodes: LocationTreeSelectNode[]): void {
        if (targetId === this.root.public_id) {
            this.dataSource.data = [...this.dataSource.data, ...movedNodes];
            return;
        }

        const target = this.nodesById.get(targetId);
        if (!target) {
            return;
        }

        target.has_children = true;

        if (target.loaded) {
            target.children$.next([...target.children$.value, ...movedNodes]);
        }
        // When not loaded, expanding lets the lazy loader fetch the authoritative post-move list.
        this.treeControl.expand(target);
    }

    /** Runs the pure drop-eligibility rules against the current node index. */
    private checkDrop(targetId: number, ids: Set<number>): DropCheck {
        return evaluateDrop(targetId, ids, this.nodesById, this.root.public_id);
    }

    /* ------------------------------------------------ HELPER FUNCTIONS ----------------------------------------------- */

    private expandAll(nodes: LocationTreeSelectNode[]): void {
        for (const node of nodes) {
            if (node.has_children) {
                this.treeControl.expand(node);
                this.expandAll(node.children$.value);
            }
        }
    }

    /**
     * Re-renders the tree by clearing and restoring the data source.
     */
    private refreshTreeRendering(): void {
        const data = this.dataSource.data;
        this.dataSource.data = [];
        this.dataSource.data = data;
    }

    private clearDropTarget(): void {
        this.dropTargetId = null;
        this.dropTargetValid = false;
        this.dropHint = null;
    }

    /** Drops the node index and any selection so the next full load rebuilds from a clean slate. */
    private resetIndex(): void {
        this.nodesById.clear();
        this.selected.clear();
    }

    private toBrowseNode(raw: LocationTreeNode): LocationTreeSelectNode {
        return this.indexNode({
            public_id: raw.public_id,
            name: raw.name,
            icon: raw.type_icon,
            parent: raw.parent,
            object_id: raw.object_id,
            has_children: raw.has_children,
            selectable: raw.type_selectable !== false,
            excluded: false,
            children$: new BehaviorSubject<LocationTreeSelectNode[]>([]),
            loaded: !raw.has_children,
            loading: false
        });
    }

    private toSearchNode(raw: LocationTreeSearchNode): LocationTreeSelectNode {
        const children = (raw.children ?? []).map((child) => this.toSearchNode(child));

        return this.indexNode({
            public_id: raw.public_id,
            name: raw.name,
            icon: raw.icon,
            parent: raw.parent,
            object_id: raw.object_id,
            has_children: children.length > 0,
            selectable: raw.type_selectable !== false,
            excluded: false,
            children$: new BehaviorSubject<LocationTreeSelectNode[]>(children),
            loaded: true,
            loading: false
        });
    }

    private indexNode(node: LocationTreeSelectNode): LocationTreeSelectNode {
        this.nodesById.set(node.public_id, node);
        return node;
    }
}
