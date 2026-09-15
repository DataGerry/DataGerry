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
import { ChangeDetectorRef, Component, EventEmitter, inject, Input, OnDestroy, OnInit, Output } from '@angular/core';
import { MatTreeNestedDataSource } from '@angular/material/tree';
import { Router } from '@angular/router';

import { BehaviorSubject, ReplaySubject, Subject } from 'rxjs';
import { debounceTime, finalize, takeUntil } from 'rxjs/operators';

import { ObjectService } from 'src/app/framework/services/object.service';
import { SidebarService } from 'src/app/layout/services/sidebar.service';

import { IpamTreeService } from './services/ipam-tree.service';
import { IpamSupernetChildrenResponse, IpamTreeNode, IpamTreeResponse } from './models/ipam-tree.types';
/* ------------------------------------------------------------------------------------------------------------------ */

@Component({
    selector: 'ipam-tree',
    templateUrl: './ipam-tree.component.html',
    styleUrls: ['./ipam-tree.component.scss'],
    standalone: false
})
export class IpamTreeComponent implements OnInit, OnDestroy {

    /**
     * One save writes more than once - the object, then its active state - and each write announces
     * itself, so the reloads are collapsed into the last one instead of reloading the tree per write.
     */
    private static readonly REFRESH_DEBOUNCE_MS = 200;

    /**
     * Sidebar expansion state forwarded from the parent sidebar.
     */
    @Input() isExpanded: boolean;
    @Input() showSidebarExpandButton: boolean = true;

    /**
     * Emits when the user clicks the sidebar expand button.
     */
    @Output() expandClicked = new EventEmitter<void>();

    childrenAccessor = (node: IpamTreeNode) => this.childStream(node);
    supernetDataSource = new MatTreeNestedDataSource<IpamTreeNode>();
    unassigned: IpamTreeNode[] = [];

    public hasSupernets: boolean = false;
    public hasUnassigned: boolean = false;
    public isLoadingTree: boolean = false;
    public selectedNodeId: number;

    /**
     * public_ids of supernets currently fetching their children (drives the inline spinner).
     */
    private loadingNodeIds = new Set<number>();

    /**
     * public_ids of the currently expanded supernets. Bound to the tree via `isExpanded`.
     */
    private expandedNodeIds = new Set<number>();

    /**
     * Children stream per node, keyed by public_id. Lazily loaded subnets are pushed into these so a
     * branch fills in place instead of the whole tree being torn down and rebuilt.
     */
    private readonly childStreams = new Map<number, BehaviorSubject<IpamTreeNode[]>>();

    private _searchString: string = '';

    /** Re-reads the tree after a network object was written elsewhere. */
    private readonly refresh$ = new Subject<void>();

    private unsubscribe: ReplaySubject<void> = new ReplaySubject<void>();

    private readonly ipamTreeService = inject(IpamTreeService);
    private readonly objectService = inject(ObjectService);
    private readonly sidebarService = inject(SidebarService);
    private readonly router = inject(Router);
    private readonly cdRef = inject(ChangeDetectorRef);

    /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnInit(): void {
        this.listenForChanges();
        this.loadTree();
    }


    public ngOnDestroy(): void {
        this.childStreams.forEach((stream) => stream.complete());
        this.childStreams.clear();
        this.refresh$.complete();
        this.unsubscribe.next();
        this.unsubscribe.complete();
    }

    /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

    /**
     * Expands or collapses a supernet, lazy-loading its children on first expand.
     *
     * @param node the supernet node being toggled
     */
    public onToggleSupernet(node: IpamTreeNode): void {
        if (this.isNodeExpanded(node)) {
            this.expandedNodeIds.delete(node.public_id);
            return;
        }

        if (node.has_children && !node.children) {
            this.loadChildren(node);
            return;
        }

        this.expandedNodeIds.add(node.public_id);
    }


    /**
     * Mirrors the tree's expansion state back onto the component, so branches opened with the
     * keyboard (ArrowLeft/ArrowRight) stay in sync with the chevron, and lazy-loads on first expand.
     *
     * @param node the supernet whose expansion changed
     * @param expanded the new expansion state
     */
    public onExpandedChange(node: IpamTreeNode, expanded: boolean): void {
        if (!expanded) {
            this.expandedNodeIds.delete(node.public_id);
            return;
        }

        this.expandedNodeIds.add(node.public_id);

        if (node.has_children && !node.children && !this.isNodeLoading(node)) {
            this.loadChildren(node);
            return;
        }

        // The branch opened over children that were already fetched, so the tree flattened itself
        // before the expansion landed. Refresh the keyboard order now that both are in place.
        this.republishTree();
    }


    /**
     * Opens the object view of the clicked node which renders its IPAM overview.
     *
     * @param publicId public_id of the clicked supernet/subnet/unassigned network
     */
    public onNodeClicked(publicId: number): void {
        this.selectedNodeId = publicId;
        this.router.navigateByUrl('/framework/object/view/' + publicId);
    }


    /**
     * Forwards the sidebar expand request to the parent sidebar.
     */
    public onSidebarExpandClicked(): void {
        this.expandClicked.emit();
    }

    /* ---------------------------------------------------- FUNCTIONS --------------------------------------------------- */

    get searchString(): string {
        return this._searchString;
    }

    set searchString(value: string) {
        this._searchString = value;
    }


    public handleSearchReset(): void {
        this._searchString = '';
    }


    /**
     * Indicates whether a node currently has its children being fetched.
     */
    public isNodeLoading(node: IpamTreeNode): boolean {
        return this.loadingNodeIds.has(node.public_id);
    }


    /**
     * Indicates whether a supernet is currently expanded.
     */
    public isNodeExpanded(node: IpamTreeNode): boolean {
        return this.expandedNodeIds.has(node.public_id);
    }


    /**
     * Tree predicate: a node is expandable when it announces children or already has them loaded.
     */
    hasChild = (_: number, node: IpamTreeNode): boolean =>
        !!node.has_children || (!!node.children && node.children.length > 0);


    /**
     * Icon for a node: a network glyph for containers (supernets/parent subnets),
     * a leaf glyph for terminal subnets and unassigned networks.
     */
    public nodeIconClass(node: IpamTreeNode): string {
        return this.hasChild(0, node) ? 'fas fa-network-wired' : 'fas fa-sitemap';
    }


    /**
     * Returns true when a leaf node should be hidden by the current search.
     */
    public filterLeafNode(node: IpamTreeNode): boolean {
        if (!this._searchString) {
            return false;
        }

        return !this.matchesSearch(node);
    }


    /**
     * Returns true when a parent node should be hidden by the current search.
     * Keeps the parent visible when it (or any already-loaded descendant) matches.
     */
    public filterParentNode(node: IpamTreeNode): boolean {
        if (!this._searchString) {
            return false;
        }

        return !this.subtreeMatchesSearch(node);
    }


    /**
     * Unassigned networks filtered by the current search string.
     */
    get filteredUnassigned(): IpamTreeNode[] {
        if (!this._searchString) {
            return this.unassigned;
        }

        return this.unassigned.filter(node => this.matchesSearch(node));
    }


    /**
     * Whether any supernet root remains visible under the current search.
     */
    get hasVisibleSupernets(): boolean {
        return this.supernetDataSource.data.some(node => !this.filterParentNode(node));
    }


    /**
     * Whether any result remains visible across both sections under the current search.
     */
    get hasSearchResults(): boolean {
        if (!this._searchString) {
            return true;
        }

        return this.hasVisibleSupernets || this.filteredUnassigned.length > 0;
    }

    /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

    /**
     * Re-reads the tree whenever a network object is written. The tree is a section of the sidebar,
     * so it reloads on the same signal the rest of it does, and on the object writes that reach the
     * networks themselves - a supernet added, renamed or deleted from anywhere in the app.
     */
    private listenForChanges(): void {
        this.sidebarService.reloaded.pipe(takeUntil(this.unsubscribe)).subscribe(() => this.refresh$.next());

        this.objectService.objectActionSource.pipe(takeUntil(this.unsubscribe))
            .subscribe(() => this.refresh$.next());

        this.refresh$
            .pipe(debounceTime(IpamTreeComponent.REFRESH_DEBOUNCE_MS), takeUntil(this.unsubscribe))
            .subscribe(() => this.loadTree(false));
    }


    /**
     * Reads the top level of the tree.
     *
     * @param showSpinner whether to blank the panel while reading. A reload triggered by a write
     *   keeps the current tree on screen instead of flashing the loading state, and re-opens the
     *   branches that were open - the node objects are replaced, so their children are gone with them.
     */
    private loadTree(showSpinner: boolean = true): void {
        this.isLoadingTree = showSpinner;

        this.ipamTreeService.getTree()
            .pipe(takeUntil(this.unsubscribe), finalize(() => {
                this.isLoadingTree = false;
                this.cdRef.markForCheck();
            }))
            .subscribe((response: IpamTreeResponse) => {
                this.resetChildStreams();
                this.supernetDataSource.data = response?.supernets ?? [];
                this.unassigned = response?.unassigned ?? [];
                this.hasSupernets = this.supernetDataSource.data.length > 0;
                this.hasUnassigned = this.unassigned.length > 0;
                this.restoreExpansion();
            });
    }


    /**
     * Re-fetches the branches that were open before a reload. One supernet read returns its whole
     * nested subtree, so re-reading the open top-level supernets restores the descendants too - the
     * deeper ids are still in `expandedNodeIds` and their children arrive inline.
     */
    private restoreExpansion(): void {
        if (!this.expandedNodeIds.size) {
            return;
        }

        for (const node of this.supernetDataSource.data) {
            if (node.has_children && !node.children && this.expandedNodeIds.has(node.public_id)) {
                this.loadChildren(node);
            }
        }
    }


    private loadChildren(node: IpamTreeNode): void {
        this.loadingNodeIds.add(node.public_id);

        this.ipamTreeService.getSupernetChildren(node.public_id)
            .pipe(takeUntil(this.unsubscribe), finalize(() => {
                this.loadingNodeIds.delete(node.public_id);
                this.cdRef.markForCheck();
            }))
            .subscribe((response: IpamSupernetChildrenResponse) => {
                node.children = response?.children ?? [];
                this.childStream(node).next(node.children);
                this.expandedNodeIds.add(node.public_id);
                this.republishTree();
            });
    }


    /**
     * Children stream for a node, created on first use and seeded with whatever the backend already
     * delivered inline.
     */
    private childStream(node: IpamTreeNode): BehaviorSubject<IpamTreeNode[]> {
        let stream = this.childStreams.get(node.public_id);

        if (!stream) {
            stream = new BehaviorSubject<IpamTreeNode[]>(node.children ?? []);
            this.childStreams.set(node.public_id, stream);
        }

        return stream;
    }


    private resetChildStreams(): void {
        this.childStreams.forEach((stream) => stream.complete());
        this.childStreams.clear();
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
            this.supernetDataSource.data = [...this.supernetDataSource.data];
        });
    }


    /**
     * Case-insensitive match against a node's name or CIDR, walking the already-loaded subtree.
     */
    private subtreeMatchesSearch(node: IpamTreeNode): boolean {
        return this.matchesSearch(node)
            || (node.children ?? []).some(child => this.subtreeMatchesSearch(child));
    }


    /**
     * Case-insensitive match against a node's name or CIDR.
     */
    private matchesSearch(node: IpamTreeNode): boolean {
        const term = this._searchString.toLowerCase();
        const name = node.name?.toLowerCase() ?? '';
        const cidr = node.cidr?.toLowerCase() ?? '';
        return name.indexOf(term) !== -1 || cidr.indexOf(term) !== -1;
    }
}
