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

* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { Component, ElementRef, HostListener, Input, OnInit, ViewChild, OnDestroy, ChangeDetectorRef, SimpleChanges, Output, EventEmitter, inject } from '@angular/core';
import { FormBuilder, FormGroup } from '@angular/forms';
import { Subject, fromEvent } from 'rxjs';
import { takeUntil, debounceTime, finalize } from 'rxjs/operators';
import { getTextColorBasedOnBackground } from 'src/app/core/utils/color-utils';
import { CI_EXPLORER_EDIT_RIGHT, CIEdge, CINode, GraphRespWithRoot } from 'src/app/framework/models/ci-explorer.model';
import { TypeService } from 'src/app/framework/services/type.service';
import { RelationService } from 'src/app/framework/services/relaion.service';

import { GraphNode, Connection, NodeGroup, FilterProfile } from './interfaces/graph.interfaces';
import { LAYOUT_CONFIG, KEYBOARD_SHORTCUTS } from './constants/graph.constants';
import { GraphDataService } from './services/graph-data.service';
import { GraphLayoutService } from './services/graph-layout.service';
import { GraphViewportService } from './services/graph-viewport.service';
import { GraphExpansionService } from './services/graph-expansion.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { NodeDetailsModalComponent } from './modals/node-details/node-details-modal.component';
import { ConnectionDetailsData, ConnectionDetailsModalComponent } from './modals/connection-details/connection-details-modal.component';
import {
  resolveDirection,
  rowsFromIndexedEdges,
  rowsFromRenderedConnection,
  rowsFromTrackedConnections,
  toNodeDetails
} from './utils/connection-modal.util';
import { visibleConnections, visibleNodes } from './utils/graph-filter.util';
import {
  calculateLabelPosition,
  calculatePath,
  getConnectionStrokeWidth,
  validateConnections
} from './utils/graph-path.util';
import { GraphProfileService } from './services/graph-profile.service';
import { ConnectionTrackerService } from './services/connection-tracker.service';
import { CiExplorerExportService } from './services/ci-explorer-export.service';
import { GraphInteractionService } from './services/graph-interaction.service';
import { GraphKeyboardService } from './services/graph-keyboard.service';
import { GraphNavigationService } from './services/graph-navigation.service';
import { GraphRootNodeService } from './services/graph-root-node.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { CI_EXPLORER_ITEM_LIMIT } from 'src/app/framework/services/ci-explorer.service';
import { FullscreenModalService } from 'src/app/core/services/fullscreen-modal.service';
import { PermissionService } from 'src/app/modules/auth/services/permission.service';

@Component({
  selector: 'app-graph-editor',
  templateUrl: './graph-editor.component.html',
  styleUrls: ['./graph-editor.component.scss'],
  providers: [GraphDataService, GraphLayoutService, GraphViewportService, GraphExpansionService, GraphRootNodeService],
  standalone: false
})
export class GraphEditorComponent implements OnInit, OnDestroy {
  @ViewChild('editorRoot') editorRoot!: ElementRef<HTMLElement>;
  @ViewChild('graphCanvas') graphCanvas!: ElementRef;
  @ViewChild('graphContainer') graphContainer!: ElementRef;
  @Input() rootNodeId: number = null;
  @Output() rootNodeSelected = new EventEmitter<number>();

  /** Filter profiles are written through the CI Explorer edit routes, so their controls need that right. */
  readonly ciExplorerEditRight = CI_EXPLORER_EDIT_RIGHT;

  // Filter state
  typesFilter: number[] = [];
  relationsFilter: number[] = [];
  relationsLoaded: boolean = false;
  typesLoaded: boolean = false;
  showFilterBar = false;
  filterForm: FormGroup;

  filterMode: 'manual' | 'profile' = 'manual';
  profiles: FilterProfile[] = [];
  selectedProfileId: number | null = null;
  withLocations: boolean = true;
  withIpamRelations: boolean = true;

  // Filter options
  typeOptionList: { public_id: number; display_name: string }[] = [];
  relationOptionList: { public_id: number; display_name: string }[] = [];

  // Core data
  nodes: GraphNode[] = [];
  connections: Connection[] = [];
  nodeGroups: NodeGroup[] = [];

  // Node type configurations
  nodeTypeConfigs = new Map<string, { icon: string; gradient: string }>();

  // Selection state
  selectedNode: GraphNode | null = null;
  selectedConnection: Connection | null = null;
  selectedNodes: Set<number> = new Set();

  // Interaction state
  isDragging = false;
  isPanning = false;
  isMultiSelecting = false;
  dragOffsetX = 0;
  dragOffsetY = 0;
  panStartX = 0;
  panStartY = 0;

  // Focus mode
  focusMode = false;
  focusedNodeId: number | null = null;

  // Menu state
  contextMenuVisible = false;
  contextMenuX = 0;
  contextMenuY = 0;

  // UI state
  hoveredNode: GraphNode | null = null;
  hoveredConnection: Connection | null = null;
  showMinimap = false;

  // Layout configuration (exposed for template)
  LAYOUT_CONFIG = LAYOUT_CONFIG;

  private destroy$ = new Subject<void>();

  private readonly permissionService = inject(PermissionService);

  /** `*permissionLink` only hides the buttons, so both profile write paths re-check the right. */
  private readonly canEditProfiles = this.permissionService.hasRight(CI_EXPLORER_EDIT_RIGHT)
    || this.permissionService.hasExtendedRight(CI_EXPLORER_EDIT_RIGHT);

  // Loader state
  public isLoading$ = this.loaderService.isLoading$;

  isFullscreen = false;

  constructor(
    private cdr: ChangeDetectorRef, private typeService: TypeService, private relationService: RelationService,
    private fb: FormBuilder, private graphData: GraphDataService, private graphLayout: GraphLayoutService,  private graphViewport: GraphViewportService,
    private graphExpansion: GraphExpansionService,
    private loaderService: LoaderService, private profileService: GraphProfileService, private modalService: NgbModal,
    private connectionTracker: ConnectionTrackerService, private exportService: CiExplorerExportService, private graphInteractionService: GraphInteractionService,
    private graphKeyboardService: GraphKeyboardService, private graphNavigationService: GraphNavigationService, private graphRootNodeService: GraphRootNodeService,
    private toastService: ToastService, private fullscreenModalService: FullscreenModalService
  ) {
    this.filterForm = this.fb?.group({
      types: [[]],
      relations: [[]]
    });
  }

  ngOnInit(): void {
    this.loadFilterOptions();
    this.setupFormSubscriptions();
    this.loadInitialGraph();
    this.setupEventListeners();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['rootNodeId'] && !changes['rootNodeId'].firstChange) {
      this.loadInitialGraph(true);
    }
  }

  ngOnDestroy(): void {
    this.destroy$?.next();
    this.destroy$?.complete();
    this.graphData?.destroy();
    this.connectionTracker?.clear();
  }

  /**
    * Sets up form subscriptions to update filter state when form values change.
    */
  private setupFormSubscriptions(): void {
    this.filterForm?.get('types')!?.valueChanges?.subscribe(v => this.typesFilter = v || []);
    this.filterForm?.get('relations')!?.valueChanges?.subscribe(v => this.relationsFilter = v || []);
  }

  /**
    * Sets up event listeners for keyboard shortcuts and window resize.
    */
  private setupEventListeners(): void {
    fromEvent<KeyboardEvent>(document, 'keydown')?.pipe(takeUntil(this.destroy$))?.subscribe(event => this.handleKeyboard(event));
    fromEvent(window, 'resize')?.pipe(debounceTime(300), takeUntil(this.destroy$))?.subscribe(() => this.handleResize());
    fromEvent(document, 'fullscreenchange')?.pipe(takeUntil(this.destroy$))?.subscribe(() => this.onFullscreenChange());
  }


  /**
  * Handles keyboard shortcuts for graph interactions.
  */
  private handleKeyboard(event: KeyboardEvent): void {
    this.graphKeyboardService.handleKeyboard(
      event,
      (e: KeyboardEvent) => this.getKeyCombo(e),
      KEYBOARD_SHORTCUTS,
      {
        navigateUp: () => this.navigateUp(),
        navigateDown: () => this.navigateDown(),
        navigateLeft: () => this.navigateLeft(),
        navigateRight: () => this.navigateRight(),
        deleteSelectedNodes: () => this.deleteSelectedNodes(),
        clearSelection: () => this.clearSelection(),
        focusOnSelected: () => this.focusOnSelected(),
        toggleExpandSelected: () => this.toggleExpandSelected(),
        selectAllNodes: () => this.selectAllNodes(),
        focusSearch: () => this.focusSearch(),
        setSelectedAsRoot: () => this.setSelectedAsRoot(),
        zoomIn: () => this.zoomIn(),
        zoomOut: () => this.zoomOut(),
        resetZoom: () => this.resetZoom()
      }
    );
  }


  /**
    * Generates a key combination string from the keyboard event.
    */
  private getKeyCombo(event: KeyboardEvent): string {
    return this.graphKeyboardService.getKeyCombo(event);
  }


  /**
   * loads the initial graph data with the root node and applies filters.
   */
  private loadInitialGraph(reset = false): void {
    if (reset) {
      this.nodes.length = 0;
      this.connections.length = 0;
      this.nodeGroups.length = 0;
      this.graphData?.clearAllData();
      this.connectionTracker.clear();
    }

    this.loaderService.show();
    this.graphData.loadWithRoot(
      this.rootNodeId,
      this.typesFilter,
      this.relationsFilter,
      this.withLocations,
      this.withIpamRelations
    ).pipe(finalize(() => this.loaderService.hide())).subscribe({
      next: r => this.paintInitial(r),
      error: err => this.showErrorNotification(err.error?.message)
    });
  }


  /**
    * Paints the initial graph data based on the response from the server.
    */
  private paintInitial(r: GraphRespWithRoot): void {
    this.nodes = [];
    this.connections = [];
    this.graphData.clearAllData();

    // Set root node
    r.root_node.level = 0;
    (r.root_node as any).direction = 'root';
    (r.root_node as any).isRoot = true;

    const parentNodes = this.graphData.getNodes(r, 'parent');
    const childNodes = this.graphData.getNodes(r, 'child');
    this.notifyLimitIfNeeded([parentNodes.length, childNodes.length]);

    // Find nodes that appear in both collections
    const parentIds = new Set(parentNodes.map(n => n.linked_object.public_id));
    const childIds = new Set(childNodes.map(n => n.linked_object.public_id));
    const duplicateIds = new Set([...parentIds].filter(id => childIds.has(id)));


    const processedNodeIds = new Set<number>();
    const finalParentNodes: CINode[] = [];
    const finalChildNodes: CINode[] = [];

    // Process parent nodes
    parentNodes.forEach((n) => {
      const id = n.linked_object.public_id;
      if (!processedNodeIds.has(id)) {
        n.level = -1;
        (n as any).direction = 'parent';
        finalParentNodes.push(n);
        processedNodeIds.add(id);
      }
    });

    // Process child nodes - INCLUDING duplicates but at child level
    childNodes.forEach((n) => {
      const id = n.linked_object.public_id;
      if (duplicateIds.has(id)) {
        // Create a separate instance for the child level
        const childCopy = { ...n };
        childCopy.level = 1;
        (childCopy as any).direction = 'child';
        finalChildNodes.push(childCopy);
      } else if (!processedNodeIds.has(id)) {
        n.level = 1;
        (n as any).direction = 'child';
        finalChildNodes.push(n);
        processedNodeIds.add(id);
      }
    });

    // Merge all nodes
    this.graphData.mergeNodes(
      this.nodes,
      [r.root_node, ...finalParentNodes, ...finalChildNodes],
      this.nodeTypeConfigs
    );

    this.graphData.mergeEdges(
      this.connections,
      this.nodes,
      [...this.graphData.getEdges(r, 'parent'), ...this.graphData.getEdges(r, 'child')]
    );

    this.connections = validateConnections(this.connections, this.graphData.getNodeInstanceMap());
    this.graphData.addExpandedNode(r.root_node.linked_object.public_id);
    this.performHierarchicalLayout();
    this.updateNodeStates();

    const allInitialEdges = [...this.graphData.getEdges(r, 'parent'), ...this.graphData.getEdges(r, 'child')];
    allInitialEdges.forEach(edge => this.graphData.storeAndIndexEdge(edge));
    this.connectionTracker.storeInitialConnections(allInitialEdges, this.graphData.getNodeInstanceMap());
    this.centerViewport();
  }


  /**
    * loads filter options for types and relations from the respective services.
    */
  private loadFilterOptions(): void {
    this.profileService.loadFilterOptions(
      this.typeService,
      this.relationService,
      this.loaderService,
      (message: string) => this.showErrorNotification(message)
    ).subscribe({
      next: (result) => {
        this.typeOptionList = result.types;
        this.relationOptionList = result.relations;
        this.typesLoaded = true;
        this.relationsLoaded = true;
      },
      error: (e) => this.showErrorNotification(e?.error?.message)
    });
  }


  /**
    * toggles the visibility of the filter bar.
    */
  toggleFilterBar(): void {
    this.showFilterBar = !this.showFilterBar;
  }


  /**
    *  clears all filters applied to the graph.
    */
  clearFilters(): void {
    this.filterForm?.patchValue({
      types: [],
      relations: []
    });
    this.typesFilter = [];
    this.relationsFilter = [];
    this.loadInitialGraph(true);
  }


  /**
    * Applies the current filters from the form to the graph data.
    */
  applyFilters(): void {
    this.typesFilter = this.filterForm?.value?.types || [];
    this.relationsFilter = this.filterForm?.value?.relations || [];
    this.loadInitialGraph(true);
    this.showFilterBar = false;
  }

  // Layout management
  private performHierarchicalLayout(): void {
    this.graphLayout?.updateAnchorCalculations(this.connections, this.graphData?.getNodeInstanceMap());
    this.graphLayout?.performHierarchicalLayout(this.nodes, this.nodeGroups);
  }


  /**
   * Updates the states of all nodes based on their connections.
   * This includes counting parent and child connections, and simulating dynamic status updates.
   */
  private updateNodeStates(): void {
    this.nodes.forEach(node => {
      let parentConnections = 0;
      let childConnections = 0;

      this.connections.forEach(conn => {
        if (!conn.isValid) return;

        // If this node is the "from" node in the connection
        if (conn.fromUid === node.uid) {
          const otherNode = this.graphData.getNodeInstanceMap().get(conn.toUid!);
          if (otherNode) {
            // If connecting to a node at a lower level (more negative), it's a parent connection
            if (otherNode.level < node.level) {
              parentConnections++;
            }
            // If connecting to a node at a higher level (more positive), it's a child connection
            else if (otherNode.level > node.level) {
              childConnections++;
            }
          }
        }

        // If this node is the "to" node in the connection
        if (conn.toUid === node.uid) {
          const otherNode = this.graphData.getNodeInstanceMap().get(conn.fromUid!);
          if (otherNode) {
            // If connected from a node at a lower level (more negative), it's a parent connection
            if (otherNode.level < node.level) {
              parentConnections++;
            }
            // If connected from a node at a higher level (more positive), it's a child connection
            else if (otherNode.level > node.level) {
              childConnections++;
            }
          }
        }
      });
      node.connectionCount = {
        parents: parentConnections,
        children: childConnections,
      };
      node.hasParents = parentConnections > 0;
      node.hasChildren = childConnections > 0;
    });
  }


  /**
   * Toggles the expansion state of a node.
   * If the node is a root or currently loading, no action is taken.
   * Otherwise, it expands or collapses the node based on its current state.
   */
  toggleExpand(node: GraphNode, event?: MouseEvent): void {
    if (event) { 
      event.stopPropagation(); // Prevent modal from opening
      }

    if (node.isLoading) return;

    if (node.isRoot) {
      this.toggleRootExpansion();
      return;
    }

    node.expanded ? this.collapseNodeInstance(node) : this.expandNodeInstance(node);
  }

  private toggleRootExpansion(): void {
    const rootNode = this.graphRootNodeService.getRootNode(this.nodes);
    if (!rootNode || rootNode.isLoading) {
      return;
    }

    if (this.graphRootNodeService.hasVisibleNodesBeyondRoot(this.nodes)) {
      const collapsed = this.graphRootNodeService.collapseRootNode(rootNode, this.nodes, this.connections);
      if (collapsed) {
        this.selectedConnection = null;
        this.performHierarchicalLayout();
        this.updateNodeStates();
      }
      return;
    }

    this.rootNodeId = rootNode.id;
    this.loadInitialGraph(true);
  }

  public getContextExpandIcon(node: GraphNode | null): string {
    return this.graphRootNodeService.getExpandIcon(node, this.nodes);
  }

  public getContextExpandLabel(node: GraphNode | null): string {
    return this.graphRootNodeService.getExpandLabel(node, this.nodes);
  }

  public onContextToggleExpand(event: MouseEvent): void {
    if (!this.selectedNode) {
      return;
    }
    this.toggleExpand(this.selectedNode, event);
    this.contextMenuVisible = false;
  }


  /**
   * Expands a node instance by fetching its children and updating the graph.
   */
  private async expandNodeInstance(ui: GraphNode): Promise<void> {
    const cn = ui.ciNode!;
    this.loaderService.show();
    try {
      await this.graphExpansion?.expandNodeInstance(
        ui, cn, this.nodes, this.connections,
        this.typesFilter, this.relationsFilter, this.nodeTypeConfigs,
        this.withLocations, this.withIpamRelations
      );

      this.connections = validateConnections(this.connections, this.graphData.getNodeInstanceMap());
      this.performHierarchicalLayout();
      this.updateNodeStates();
    } finally {
      this.loaderService.hide();
      this.cdr.detectChanges();
    }
  }


  /**
   * Collapses a node instance, removing its children and updating the graph.
   */
  private collapseNodeInstance(ui: GraphNode): void {
    this.graphExpansion?.collapseNodeInstance(ui, this.nodes, this.connections);
    this.performHierarchicalLayout();
    this.updateNodeStates();
  }

  // Viewport management
  get viewportX(): number { return this.graphViewport?.getViewportX(); }
  get viewportY(): number { return this.graphViewport?.getViewportY(); }
  get zoom(): number { return this.graphViewport?.getZoom(); }


  /**
  * Centers the viewport on the current graph data.
  * This method adjusts the viewport to fit all nodes within the visible area.
  */
  centerViewport(): void {
    this.graphViewport?.centerViewport(this.graphContainer, this.nodes);
  }


  /**
  * Zooms in on the graph, increasing the scale of the viewport.
  */
  zoomIn(): void {
    this.graphViewport?.zoomIn();
  }


  /**
  * Zooms out of the graph, decreasing the scale of the viewport.
  */
  zoomOut(): void {
    this.graphViewport?.zoomOut();
  }


  /**
  * Resets the zoom level of the graph to its default state.
  */
  resetZoom(): void {
    this.graphViewport?.resetZoom(this.graphContainer, this.nodes);
  }


  /**
    * Centers the viewport on a specific node.
    */
  centerOnNode(node: GraphNode): void {
    this.graphViewport?.centerOnNode(node, this.graphContainer);
  }


  /**
   * Determines if a node should be shown based on the current viewport and graph state.
   */
  shouldShowNode(node: GraphNode): boolean {
    return this.graphViewport?.shouldShowNode(node, this.nodes?.length, this.graphContainer);
  }


  /**
    * Calculates the path for a connection based on the graph data.
    */
  calculatePath(conn: Connection): string {
    return calculatePath(conn, this.graphData.getNodeInstanceMap());
  }


  /**
   * Calculates the label position for a connection based on the graph data.
   */
  calculateLabelPosition(conn: Connection): { x: number; y: number } {
    return calculateLabelPosition(conn, this.nodes);
  }


  /**
   * Gets the stroke width for a connection based on its properties.
   */
  getConnectionStrokeWidth(conn: Connection): number {
    return getConnectionStrokeWidth(conn);
  }


  /**
    * Filters the nodes based on the current graph filter settings.
    */
  get filteredNodes(): GraphNode[] {
    return visibleNodes(this.nodes);
  }


  /**
   * Gets the visible connections based on the current graph filter settings.
   */
  getVisibleConnections(): Connection[] {
    return visibleConnections(this.filteredNodes, this.connections);
  }


  /**
   * Selects a node and opens the details modal.
   * If the event is a right-click or comes from a button, it skips opening the modal.
   */
  selectNode(node: GraphNode, event?: MouseEvent): void {

    // Check if this is a right-click or if event came from a button
    if (event && (event.button === 2 || event.target && (event.target as HTMLElement).closest('.action-btn'))) {
      return;
    }

    if (!this.isMultiSelecting) {
      this.clearSelection();
    }
    this.selectedNode = node;
    this.selectedNodes.add(node?.id);

    // Show the modal using NgBootstrap
    this.openNodeDetailsModal(node);
  }


  /**
   * Opens the node details modal with the selected node.
   */
  toggleNodeSelection(node: GraphNode): void {
    if (this.selectedNodes?.has(node?.id)) {
      this.selectedNodes?.delete(node?.id);
      if (this.selectedNode?.id === node?.id) {
        this.selectedNode = null;
      }
    } else {
      this.selectedNodes.add(node?.id);
      this.selectedNode = node;
    }
  }


  /** 
  * Selects all nodes in the graph, adding them to the selectedNodes set.
  */
  selectAllNodes(): void {
    this.nodes?.forEach(n => this.selectedNodes.add(n?.id));
  }


  /**
    * Clears the current selection of nodes and connections.
    */
  clearSelection(): void {
    this.selectedNodes.clear();
    this.selectedNode = null;
    this.selectedConnection = null;
  }


  /**
   * Selects a connection and clears any selected nodes.
   */
  selectConnection(conn: Connection): void {
    this.selectedConnection = conn;
    this.selectedNode = null;
    this.selectedNodes?.clear();
  }


  /**
    * Navigates through the nodes in the specified direction.
    */
  navigateNodes(direction: 'up' | 'down' | 'left' | 'right'): void {
    this.graphNavigationService.navigateNodes(
      direction,
      this.selectedNode,
      this.nodes,
      (node: GraphNode) => this.selectNode(node),
      (node: GraphNode) => this.centerOnNode(node),
      (from: GraphNode, dx: number, dy: number) => this.findNodeInDirection(from, dx, dy)
    );
  }


  /**
    * Finds the closest node in the specified direction from the given node.
    */
  private findNodeInDirection(from: GraphNode, dx: number, dy: number): GraphNode | undefined {
    const candidates = this.nodes?.filter(n => n?.id !== from?.id);

    if (dy !== 0) {
      const targetLevel = from.level + dy;
      const levelNodes = candidates?.filter(n => n?.level === targetLevel);
      if (levelNodes.length > 0) {
        return levelNodes?.reduce((closest, node) => {
          const closestDist = Math.abs(closest?.x - from?.x);
          const nodeDist = Math.abs(node?.x - from?.x);
          return nodeDist < closestDist ? node : closest;
        });
      }
    } else {
      const levelNodes = candidates?.filter(n => n?.level === from?.level);
      const directionNodes = levelNodes?.filter(n =>
        dx > 0 ? n?.x > from?.x : n?.x < from?.x
      );
      if (directionNodes.length > 0) {
        return directionNodes?.reduce((closest, node) => {
          const closestDist = Math.abs(closest?.x - from?.x);
          const nodeDist = Math.abs(node?.x - from?.x);
          return nodeDist < closestDist ? node : closest;
        });
      }
    }
    return undefined;
  }


  /**
    * Toggles the focus mode for the graph.
    */
  toggleFocusMode(): void {
    this.focusMode = !this.focusMode;
    if (this.focusMode && this.selectedNode) {
      this.focusedNodeId = this.selectedNode?.id;
      this.centerOnNode(this.selectedNode);
    } else {
      this.focusedNodeId = null;
    }
  }


  /**
    * Focuses on the currently selected node if it exists.
    */
  focusOnSelected(): void {
    if (this.selectedNode) {
      this.toggleFocusMode();
    }
  }


  /**
    * Handles mouse down events on a node.
    */
  onNodeMouseDown(e: MouseEvent, node: GraphNode): void {
    const result = this.graphInteractionService.onNodeMouseDown(
      e, node, this.isDragging, this.isMultiSelecting, this.selectedNodes, this.dragOffsetX, this.dragOffsetY,
      (n: GraphNode) => this.toggleNodeSelection(n), (n: GraphNode, ev?: MouseEvent) => this.selectNode(n, ev));

    this.isDragging = result.isDragging;
    this.isMultiSelecting = result.isMultiSelecting;
    this.selectedNodes = result.selectedNodes;
    this.dragOffsetX = result.dragOffsetX;
    this.dragOffsetY = result.dragOffsetY;
  }


  /**
  * Handles mouse down events on the canvas for panning.
  */
  onCanvasMouseDown(e: MouseEvent): void {
    const result = this.graphInteractionService.onCanvasMouseDown(
      e, this.isPanning, this.panStartX, this.panStartY, this.viewportX, this.viewportY, () => this.clearSelection()
    );

    this.isPanning = result.isPanning;
    this.panStartX = result.panStartX;
    this.panStartY = result.panStartY;
  }


  @HostListener('wheel', ['$event'])
  onWheel(e: WheelEvent): void {
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault();
      const delta = e.deltaY > 0 ? 0.9 : 1.1;
      this.graphViewport.setZoomWithDelta(delta);
    }
  }


  @HostListener('document:mousemove', ['$event'])
  onMouseMove(e: MouseEvent): void {
    if (this.isPanning) {
      this.graphViewport?.setViewport(
        e?.clientX - this.panStartX,
        e?.clientY - this.panStartY
      );
    }
  }


  @HostListener('document:mouseup')
  onMouseUp(): void {
    this.isDragging = false;
    this.isPanning = false;
    this.isMultiSelecting = false;
  }

  /**
  * Handles right-click events on a node to show the context menu.
  */
  onRightClick(e: MouseEvent, node: GraphNode): void {
    const result = this.graphInteractionService.onRightClick(
      e, node, this.selectedNode, this.selectedNodes, this.contextMenuX, this.contextMenuY, this.contextMenuVisible, false
    );

    this.selectedNode = result.selectedNode;
    this.selectedNodes = result.selectedNodes;
    this.contextMenuX = result.contextMenuX;
    this.contextMenuY = result.contextMenuY;
    this.contextMenuVisible = result.contextMenuVisible;
  }

  onGraphContextMenu(e: MouseEvent): void {
    e.preventDefault();
  }

  @HostListener('document:click', ['$event'])
  docClick(e: MouseEvent): void {
    if (!(e.target as Element).closest('.context-menu')) {
      this.contextMenuVisible = false;
    }
  }


  /**
  * Selects the current node as the root node for the graph.
  */
  selectAsRootNode(): void {
    if (this.selectedNode) {
      this.rootNodeId = this.selectedNode?.id;
      this.rootNodeSelected.emit(this.rootNodeId);
      this.loadInitialGraph();
    }
    this.contextMenuVisible = false;
  }

  /**
  * Sets the selected node as the root node of the graph.
  */
  setSelectedAsRoot(): void {
    if (this.selectedNode) {
      this.selectAsRootNode();
    }
  }

  /**
  * Deletes the currently selected nodes from the graph.
  */
  deleteSelectedNodes(): void {
    if (this.selectedNodes?.size > 0) {
      const toDelete = new Set(this.selectedNodes);
      this.removeNodesAndConnections(toDelete);
      this.clearSelection();
      this.performHierarchicalLayout();
      this.showNotification(`Deleted ${toDelete.size} node(s)`);
    }
  }

  toggleExpandSelected(): void {
    if (this.selectedNode) {
      this.toggleExpand(this.selectedNode);
    }
  }

  private removeNodesAndConnections(toDelete: Set<number>): void {
    this.nodes = this.nodes?.filter(n => !toDelete?.has(n?.id));
    this.connections = this.connections?.filter(
      c => !toDelete?.has(c?.from) && !toDelete?.has(c?.to)
    );

    toDelete?.forEach(id => {
      this.selectedNodes?.delete(id);
    });
  }

  // UI toggles

  toggleMinimap(): void {
    this.showMinimap = !this.showMinimap;
  }

  // Template helpers
  get Object() {
    return Object;
  }


  /**
   * Gets the configuration for a specific node type.
   */
  getNodeTypeConfig(type: string): { icon: string; gradient: string } {
    return this.nodeTypeConfigs?.get(type);
  }


  /**
   * Gets a node by its ID.
   */
  getNodeById(id: number): GraphNode | undefined {
    return this.nodes?.find(n => n?.id === id);
  }


  /**
   * Gets a node by its ID and level.
   */
  getNodeByIdAndLevel(id: number, level: number): GraphNode | undefined {
    return this.nodes?.find(n => n?.id === id && n?.level === level);
  }


  /**
   * Checks if a node sits at either end of the hovered connection.
   */
  isNodeHighlighted(node: GraphNode): boolean {
    return !!this.hoveredConnection &&
      (this.hoveredConnection?.from === node?.id ||
        this.hoveredConnection?.to === node?.id);
  }


  /**
   * Checks if a connection is highlighted based on the hovered or selected node.
   */
  isConnectionHighlighted(conn: Connection): boolean {
    return (this.hoveredNode &&
      (conn?.from === this.hoveredNode?.id ||
        conn?.to === this.hoveredNode?.id)) ||
      (this.selectedNode &&
        (conn?.from === this.selectedNode?.id ||
          conn?.to === this.selectedNode?.id));
  }


  /**
    * Gets the text color based on the background color of a node.
    */
  public getTextColor(node: GraphNode): string {
    return getTextColorBasedOnBackground(node?.color);
  }


  /**
    * Gets the viewBox attribute for the minimap.
    */
  getMinimapViewBox(): string {
    return this.graphViewport?.getMinimapViewBox(this.nodes);
  }


  /**
    * Gets the viewport rectangle for the minimap.
    */
  getMinimapViewportRect(): any {
    return this.graphViewport?.getMinimapViewportRect(this.graphContainer);
  }


  /**
    * Handles click events on the minimap.
    */
  onMinimapClick(event: MouseEvent): void {
    this.graphViewport?.onMinimapClick(event, this.nodes, this.graphContainer);
  }


  /** The hint banner is reserved for large graphs; below the threshold it renders empty. */
  get showPerformanceHints(): boolean {
    return this.nodes?.length > 100;
  }


  /**
   * Gets a performance hint based on the size of the graph.
   */
  getPerformanceHint(): string {
    const nodeCount = this.nodes?.length ?? 0;
    return nodeCount > 500
      ? `Displaying ${nodeCount} nodes. Use filters for better performance.`
      : '';
  }


  /**
    * Open the node details modal with the given node.
    */
  private openNodeDetailsModal(node: GraphNode): void {
    const modalRef = this.fullscreenModalService.open(this.modalService, NodeDetailsModalComponent, {
      size: 'xl',
      backdrop: 'static',
      scrollable: true,
      windowClass: 'dg-modal-window',
      backdropClass: 'dg-modal-window-backdrop'
    });

    modalRef.componentInstance.loadNode(node);
    modalRef.componentInstance.nodeTypeConfigs = this.nodeTypeConfigs;

    modalRef.result.catch(() => {/*  closed the modal */ });
  }


  /**
   * Opens the profile manager modal to manage filter profiles.
   */
  openProfileManager(): void {
    if (!this.canEditProfiles) {
      return;
    }

    this.profileService.openProfileManager(
      this.modalService,
      this.typeOptionList,
      this.relationOptionList,
      () => this.loadProfiles()
    );
  }


  /**
   * Updates the "include locations" preference used for graph API calls.
   */
  onWithLocationsChange(checked: boolean): void {
    this.withLocations = checked;
  }


  /**
   * Updates the "include IPAM relations" preference used for graph API calls.
   */
  onWithIpamRelationsChange(checked: boolean): void {
    this.withIpamRelations = checked;
  }


  /**
   * Switches the filter mode between manual and profile-based filtering.
   */
  switchFilterMode(mode: 'manual' | 'profile'): void {
    this.filterMode = mode;
    if (mode === 'profile') {
      this.loadProfiles();
    }
  }


  /**
   * Loads the available profiles from the profile service.
   */
  private loadProfiles(): void {
    this.loaderService.show();
    this.profileService.getProfiles()
      .pipe(finalize(() => this.loaderService.hide()))
      .subscribe({
        next: profiles => this.profiles = profiles,
        error: (err) => this.showErrorNotification(err?.error?.message)
      });
  }


  /**
   * Applies the selected profile's filters to the graph.
   */
  applyProfile(): void {
    const result = this.profileService.applyProfile(
      this.profiles,
      this.selectedProfileId,
      this.typesFilter,
      this.relationsFilter,
      (reset: boolean) => this.loadInitialGraph(reset),
      (message: string, type: 'info' | 'success' | 'error') => this.showNotification(message, type)
    );

    this.typesFilter = result.typesFilter;
    this.relationsFilter = result.relationsFilter;
    this.loadInitialGraph(true);
    this.showFilterBar = false;
  }


  /**
   * Saves the current filters as a new profile.
   */
  saveCurrentFiltersAsProfile(): void {
    if (!this.canEditProfiles) {
      return;
    }

    this.profileService.saveCurrentFiltersAsProfile(
      this.modalService,
      this.typeOptionList,
      this.relationOptionList,
      this.typesFilter,
      this.relationsFilter,
      () => this.hasActiveFilters(),
      (message: string, type: 'info' | 'success' | 'error') => this.showNotification(message, type)
    );
  }


  /**
   *  Handles click events on a connection.
   */
  onConnectionClick(conn: Connection, e: MouseEvent): void {
    e.stopPropagation();

    const fromNode = this.getNodeByUid(conn.fromUid!);
    const toNode = this.getNodeByUid(conn.toUid!);

    if (!fromNode || !toNode) {
      return;
    }

    this.openConnectionDetailsModal(fromNode, toNode, this.resolveConnectionRows(conn, fromNode, toNode));
  }


  /**
   * Picks the richest description of the clicked edge: the edge index first, then the
   * per-instance tracker, and finally whatever the rendered edge itself carries.
   */
  private resolveConnectionRows(
    conn: Connection,
    fromNode: GraphNode,
    toNode: GraphNode
  ): ConnectionDetailsData[] {
    const indexed = this.graphData.getAllEdgesBetween(conn.from, conn.to);
    if (indexed.length > 0) {
      return rowsFromIndexedEdges(indexed, fromNode, toNode);
    }

    if (conn.fromUid && conn.toUid) {
      const tracked = this.connectionTracker.getConnectionsBetweenUids(conn.fromUid, conn.toUid);
      if (tracked.length > 0) {
        return rowsFromTrackedConnections(tracked, fromNode, toNode);
      }
    }

    return rowsFromRenderedConnection(conn, fromNode, toNode);
  }


  /**
   * Opens the connection details modal for one edge between two rendered nodes.
   */
  private openConnectionDetailsModal(
    fromNode: GraphNode,
    toNode: GraphNode,
    connections: ConnectionDetailsData[]
  ): void {
    const modalRef = this.fullscreenModalService.open(this.modalService, ConnectionDetailsModalComponent, {
      size: 'lg',
      backdrop: 'static',
      scrollable: true,
      windowClass: 'dg-modal-window',
      backdropClass: 'dg-modal-window-backdrop'
    });

    modalRef.componentInstance.sourceNode = toNodeDetails(fromNode);
    modalRef.componentInstance.targetNode = toNodeDetails(toNode);
    modalRef.componentInstance.connections = connections;
    modalRef.componentInstance.direction = resolveDirection(fromNode, toNode);
  }


  /**
   * Checks if there are any active filters applied to the graph.
   */
  hasActiveFilters(): boolean {
    return this.profileService.hasActiveFilters(this.typesFilter, this.relationsFilter);
  }


  /**
   *  Gets a node by its UID from the graph data.
   */
  private getNodeByUid(uid: string): GraphNode | undefined {
    return this.graphData.getNodeInstanceMap().get(uid);
  }


  /**
  * trackBy for nodes: prevents re-rendering unchanged nodes
  */
  trackByNodeId(_index: number, node: GraphNode): number {
    return node.id;
  }


  /**
    * trackBy for connections: use a stable key per edge
    */
  trackByConnKey(_index: number, conn: Connection): string {
    return `${conn.from}-${conn.to}-${conn.relationLabel}`;
  }

  // Utility methods
  private handleResize(): void {
    this.centerViewport();
  }

  private showNotification(message: string, type: 'info' | 'success' | 'error' = 'info'): void {
  }

  private showErrorNotification(message: string): void {
    this.showNotification(message, 'error');
  }

  private notifyLimitIfNeeded(counts: number[]): void {
    if (counts.some(count => count >= CI_EXPLORER_ITEM_LIMIT)) {
      this.toastService.info(
        `Showing only the first ${CI_EXPLORER_ITEM_LIMIT} nodes for this level. We can't show all results.`
      );
    }
  }

  // Navigation keyboard shortcuts
  navigateUp(): void { this.navigateNodes('up'); }
  navigateDown(): void { this.navigateNodes('down'); }
  navigateLeft(): void { this.navigateNodes('left'); }
  navigateRight(): void { this.navigateNodes('right'); }

  /** Bound to Ctrl+F only to keep the browser's find bar from opening over the canvas. */
  focusSearch(): void {
  }

  /**
   * Calculates arrow position at the end of connection
   */
  getArrowPosition(conn: Connection): { x: number; y: number } {
    const fromNode = this.getNodeByUid(conn.fromUid!);
    const toNode = this.getNodeByUid(conn.toUid!);

    if (!fromNode || !toNode) {
      return { x: 0, y: 0 };
    }

    const nodeWidth = this.LAYOUT_CONFIG.nodeWidth;
    const nodeHeight = this.LAYOUT_CONFIG.nodeHeight;

    const fromCenterX = fromNode.x + nodeWidth / 2;
    const fromCenterY = fromNode.y + nodeHeight / 2;
    const toCenterX = toNode.x + nodeWidth / 2;
    const toCenterY = toNode.y + nodeHeight / 2;

    const dx = toCenterX - fromCenterX;
    const dy = toCenterY - fromCenterY;
    const distance = Math.sqrt(dx * dx + dy * dy);

    if (distance === 0) return { x: toCenterX, y: toCenterY };

    const normalX = dx / distance;
    const normalY = dy / distance;
    // Position at the edge of target node where arrow should be
    const offsetDistance = 60; // Approximate distance from node center to arrow

    return {
      x: toCenterX - normalX * offsetDistance,
      y: toCenterY - normalY * offsetDistance
    };
  }


  exportGraphAsImage(): void {
    this.exportService.exportGraphAsImage(
      this.graphCanvas?.nativeElement,
      this.loaderService,
      (message: string, type: 'info' | 'success' | 'error') => this.showNotification(message, type),
      (message: string) => this.showErrorNotification(message)
    );
  }


  async toggleFullscreen(): Promise<void> {
    if (!document.fullscreenEnabled || !this.editorRoot?.nativeElement) {
      this.showErrorNotification('Fullscreen is not available in this browser.');
      return; }

    try {
      if (this.isFullscreen && document.fullscreenElement) {
        await document.exitFullscreen();
      } else { await this.editorRoot.nativeElement.requestFullscreen();}
    } catch { this.showErrorNotification('Unable to toggle fullscreen mode.'); } }

  private onFullscreenChange(): void {
    this.isFullscreen = document.fullscreenElement === this.editorRoot?.nativeElement;
    this.handleResize();
    this.cdr.markForCheck();
  }
}
