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
import { NestedTreeControl } from '@angular/cdk/tree';
import { MatTreeNestedDataSource } from '@angular/material/tree';
import { Router } from '@angular/router';

import { ReplaySubject } from 'rxjs';
import { finalize, takeUntil } from 'rxjs/operators';

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
     * Sidebar expansion state forwarded from the parent sidebar.
     */
    @Input() isExpanded: boolean;
    @Input() showSidebarExpandButton: boolean = true;

    /**
     * Emits when the user clicks the sidebar expand button.
     */
    @Output() expandClicked = new EventEmitter<void>();

    treeControl = new NestedTreeControl<IpamTreeNode>(node => node.children);
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

    private _searchString: string = '';

    private unsubscribe: ReplaySubject<void> = new ReplaySubject<void>();

    private readonly ipamTreeService = inject(IpamTreeService);
    private readonly router = inject(Router);
    private readonly cdRef = inject(ChangeDetectorRef);

    /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

    public ngOnInit(): void {
        this.loadTree();
    }


    public ngOnDestroy(): void {
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
        if (this.treeControl.isExpanded(node)) {
            this.treeControl.collapse(node);
            return;
        }

        if (node.has_children && !node.children) {
            this.loadChildren(node);
            return;
        }

        this.treeControl.expand(node);
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

        if (this.matchesSearch(node)) {
            return false;
        }

        const descendants = this.treeControl.getDescendants(node);
        return !descendants.some(descendant => this.matchesSearch(descendant));
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

    private loadTree(): void {
        this.isLoadingTree = true;

        this.ipamTreeService.getTree()
            .pipe(takeUntil(this.unsubscribe), finalize(() => {
                this.isLoadingTree = false;
                this.cdRef.markForCheck();
            }))
            .subscribe((response: IpamTreeResponse) => {
                this.supernetDataSource.data = response?.supernets ?? [];
                this.unassigned = response?.unassigned ?? [];
                this.hasSupernets = this.supernetDataSource.data.length > 0;
                this.hasUnassigned = this.unassigned.length > 0;
            });
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
                this.refreshSupernetTree();
                this.treeControl.expand(node);
            });
    }


    /**
     * Reassigns the data source so the nested tree re-renders newly loaded children.
     */
    private refreshSupernetTree(): void {
        const data = this.supernetDataSource.data;
        this.supernetDataSource.data = [];
        this.supernetDataSource.data = data;
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
