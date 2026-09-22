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
import {
  AfterViewInit,
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  computed,
  ElementRef,
  EventEmitter,
  inject,
  Input,
  OnChanges,
  OnDestroy,
  OnInit,
  Output,
  SimpleChanges,
  ViewChild
} from '@angular/core';
import { FormBuilder, FormGroup } from '@angular/forms';
import { fromEvent, Subject } from 'rxjs';
import { debounceTime, finalize, takeUntil } from 'rxjs/operators';

import { LoaderService } from 'src/app/core/services/loader.service';
import { FullscreenModalService } from 'src/app/core/services/fullscreen-modal.service';
import { CI_EXPLORER_EDIT_RIGHT, CiExplorerScope } from 'src/app/framework/models/ci-explorer.model';
import { RelationService } from 'src/app/framework/services/relaion.service';
import { TypeService } from 'src/app/framework/services/type.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { PermissionService } from 'src/app/modules/auth/services/permission.service';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';

import { KEYBOARD_SHORTCUTS } from './constants/graph.constants';
import { GraphCanvasComponent } from './components/graph-canvas/graph-canvas.component';
import { EdgeKindCounts } from './components/graph-legend/graph-legend.component';
import { Connection, FilterProfile, GraphNode, NodeGroup } from './interfaces/graph.interfaces';
import {
  ConnectionDetailsData,
  ConnectionDetailsModalComponent
} from './modals/connection-details/connection-details-modal.component';
import { CiExplorerLabelModalComponent } from './modals/ci-explorer-label/ci-explorer-label-modal.component';
import { NodeDetailsModalComponent } from './modals/node-details/node-details-modal.component';
import { CiExplorerExportService } from './services/ci-explorer-export.service';
import { ConnectionTrackerService } from './services/connection-tracker.service';
import { GraphDataService } from './services/graph-data.service';
import { GraphEditorStore } from './services/graph-editor.store';
import { GraphExpansionService } from './services/graph-expansion.service';
import { GraphProfileService } from './services/graph-profile.service';
import { GraphViewportService, MinimapViewportRect } from './services/graph-viewport.service';
import { GraphLayoutService } from './services/layout/graph-layout.service';
import {
  resolveDirection,
  rowsFromIndexedEdges,
  rowsFromRenderedConnection,
  rowsFromTrackedConnections,
  toNodeDetails
} from './utils/connection-modal.util';

/** Arrow-key steps: dx moves along a level, dy across levels. */
const NAVIGATION_STEPS: Record<'up' | 'down' | 'left' | 'right', readonly [number, number]> = {
  up: [0, -1],
  down: [0, 1],
  left: [-1, 0],
  right: [1, 0]
};

type ShortcutAction = (typeof KEYBOARD_SHORTCUTS)[keyof typeof KEYBOARD_SHORTCUTS];

/**
 * The CI Explorer canvas. The graph itself lives in GraphEditorStore; this shell owns the
 * view concerns around it - viewport, pointer and keyboard input, menus, modals and the
 * filter bar.
 */
@Component({
  selector: 'app-graph-editor',
  templateUrl: './graph-editor.component.html',
  styleUrls: ['./graph-editor.component.scss'],
  providers: [
    GraphEditorStore,
    GraphDataService,
    GraphLayoutService,
    GraphViewportService,
    GraphExpansionService,
    ConnectionTrackerService
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  standalone: false
})
export class GraphEditorComponent implements OnInit, AfterViewInit, OnChanges, OnDestroy {
  @ViewChild('editorRoot') editorRoot!: ElementRef<HTMLElement>;
  @ViewChild('graphContainer') graphContainer!: ElementRef;
  @ViewChild(GraphCanvasComponent) canvas?: GraphCanvasComponent;

  /** Handed to the canvas after view init; binding the query itself would read it too early. */
  containerRef: ElementRef | null = null;

  @Input() rootNodeId: number = null;
  @Output() rootNodeSelected = new EventEmitter<number>();

  readonly store = inject(GraphEditorStore);

  /** How many of each edge kind are on screen, which is what the legend explains. */
  readonly edgeKindCounts = computed<EdgeKindCounts>(() => {
    const counts: EdgeKindCounts = {};

    this.store.visibleConnections().forEach(conn => {
      const kind = conn.kind ?? 'unknown';
      counts[kind] = (counts[kind] ?? 0) + 1;
    });

    return counts;
  });

  // Filter bar
  showFilterBar = false;
  filterForm: FormGroup;
  filterMode: 'manual' | 'profile' = 'manual';
  selectedProfileId: number | null = null;
  typeOptionList: { public_id: number; display_name: string }[] = [];
  relationOptionList: { public_id: number; display_name: string }[] = [];

  // Pointer interaction
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

  // Menus and panels
  contextMenuVisible = false;
  contextMenuX = 0;
  contextMenuY = 0;
  showMinimap = false;
  showLegend = true;
  isFullscreen = false;

  private readonly destroy$ = new Subject<void>();

  /** Keyed by the action names in KEYBOARD_SHORTCUTS, so an unmapped shortcut fails to compile. */
  private readonly keyboardActions: Record<ShortcutAction, () => void> = {
    deleteSelectedNodes: () => this.deleteSelectedNodes(),
    clearSelection: () => this.clearSelection(),
    focusOnSelected: () => this.focusOnSelected(),
    toggleExpandSelected: () => this.toggleExpandSelected(),
    navigateUp: () => this.navigateUp(),
    navigateDown: () => this.navigateDown(),
    navigateLeft: () => this.navigateLeft(),
    navigateRight: () => this.navigateRight(),
    selectAllNodes: () => this.selectAllNodes(),
    focusSearch: () => this.focusSearch(),
    setSelectedAsRoot: () => this.setSelectedAsRoot(),
    zoomIn: () => this.zoomIn(),
    zoomOut: () => this.zoomOut(),
    resetZoom: () => this.resetZoom()
  };
  private readonly permissionService = inject(PermissionService);
  private readonly toastService = inject(ToastService);

  /** `*permissionLink` only hides the buttons, so every write path re-checks the right. */
  private readonly canEdit = this.permissionService.hasRight(CI_EXPLORER_EDIT_RIGHT)
    || this.permissionService.hasExtendedRight(CI_EXPLORER_EDIT_RIGHT);

  constructor(
    private cdr: ChangeDetectorRef,
    private typeService: TypeService,
    private relationService: RelationService,
    private fb: FormBuilder,
    private graphData: GraphDataService,
    private graphLayout: GraphLayoutService,
    private graphViewport: GraphViewportService,
    private loaderService: LoaderService,
    private profileService: GraphProfileService,
    private modalService: NgbModal,
    private connectionTracker: ConnectionTrackerService,
    private exportService: CiExplorerExportService,
    private fullscreenModalService: FullscreenModalService
  ) {
    this.filterForm = this.fb.group({
      types: [[]],
      relations: [[]]
    });
  }

  /* --------------------------------------------------- LIFE CYCLE --------------------------------------------------- */

  ngOnInit(): void {
    // Node positions are eased in place, so an OnPush view has to be told on each frame.
    this.graphLayout.setFrameCallback(() => this.refresh());
    // Zoom eases on its own loop, and a service field changing never marks this view dirty.
    this.graphViewport.setFrameCallback(() => this.cdr.markForCheck());
    // A freshly painted graph is centred on the canvas, as it was before the split.
    this.store.setPaintedCallback(() => this.centerViewport());

    this.store.rootNodeId = this.rootNodeId;
    this.loadFilterOptions();
    this.setupFormSubscriptions();
    this.store.load();
    this.setupEventListeners();
  }

  ngAfterViewInit(): void {
    this.containerRef = this.graphContainer ?? null;
    this.cdr.markForCheck();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['rootNodeId'] && !changes['rootNodeId'].firstChange) {
      this.store.rootNodeId = this.rootNodeId;
      this.store.load(true);
    }
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
    this.graphData.destroy();
    this.connectionTracker.clear();
  }

  /* --------------------------------------------------- GRAPH VIEW --------------------------------------------------- */

  get nodes(): GraphNode[] { return this.store.nodes; }
  get nodeGroups(): NodeGroup[] { return this.store.nodeGroups; }

  get selectedNode(): GraphNode | null { return this.store.selectedNode; }
  get selectedNodes(): Set<number> { return this.store.selectedNodes; }

  get profiles(): FilterProfile[] { return this.store.profiles; }
  get scope(): CiExplorerScope { return this.store.scope; }
  get isLoading$() { return this.store.isLoading$; }

  get showPerformanceHints(): boolean { return this.store.nodes.length > 100; }
  getPerformanceHint(): string { return this.store.performanceHint(); }

  /* ---------------------------------------------------- VIEWPORT ---------------------------------------------------- */

  get viewportX(): number { return this.graphViewport.getViewportX(); }
  get viewportY(): number { return this.graphViewport.getViewportY(); }
  get zoom(): number { return this.graphViewport.getZoom(); }

  centerViewport(): void { this.graphViewport.centerViewport(this.graphContainer, this.nodes); }
  zoomIn(): void { this.graphViewport.zoomIn(); }
  zoomOut(): void { this.graphViewport.zoomOut(); }
  resetZoom(): void { this.graphViewport.resetZoom(this.graphContainer, this.nodes); }
  centerOnNode(node: GraphNode): void { this.graphViewport.centerOnNode(node, this.graphContainer); }

  getMinimapViewBox(): string { return this.graphViewport.getMinimapViewBox(this.nodes); }
  getMinimapViewportRect(): MinimapViewportRect | null {
    return this.graphViewport.getMinimapViewportRect(this.graphContainer);
  }

  onMinimapClick(event: MouseEvent): void {
    this.graphViewport.onMinimapClick(event, this.nodes, this.graphContainer);
  }

  /* ---------------------------------------------------- EVENTS ------------------------------------------------------ */

  selectNode(node: GraphNode, event?: MouseEvent): void {
    if (event && (event.button === 2 || (event.target as HTMLElement)?.closest('.action-btn'))) {
      return;
    }

    this.store.select(node, this.isMultiSelecting);
    this.openNodeDetailsModal(node);
  }

  toggleNodeSelection(node: GraphNode): void { this.store.toggleNodeSelection(node); }
  selectAllNodes(): void { this.store.selectAll(); }
  clearSelection(): void { this.store.clearSelection(); }

  async toggleExpand(node: GraphNode, event?: MouseEvent): Promise<void> {
    event?.stopPropagation();
    await this.store.toggleExpand(node);
    this.refresh();
  }

  toggleExpandSelected(): void {
    if (this.selectedNode) {
      void this.toggleExpand(this.selectedNode);
    }
  }

  getContextExpandIcon(node: GraphNode | null): string { return this.store.expandIcon(node); }
  getContextExpandLabel(node: GraphNode | null): string { return this.store.expandLabel(node); }

  onContextToggleExpand(event: MouseEvent): void {
    if (!this.selectedNode) {
      return;
    }
    void this.toggleExpand(this.selectedNode, event);
    this.contextMenuVisible = false;
  }

  onNodeMouseDown(e: MouseEvent, node: GraphNode): void {
    if (e.button !== 0 || node.isLoading) {
      return;
    }

    // A press on an action button belongs to that button, not to the drag.
    if ((e.target as HTMLElement)?.closest('.action-btn')) {
      e.stopPropagation();
      return;
    }

    e.stopPropagation();
    this.isDragging = true;
    this.isMultiSelecting = e.shiftKey || e.ctrlKey;

    if (this.isMultiSelecting) {
      this.toggleNodeSelection(node);
    } else if (!this.selectedNodes.has(node.id)) {
      this.selectNode(node, e);
    }

    this.dragOffsetX = e.clientX - node.x;
    this.dragOffsetY = e.clientY - node.y;
  }

  onCanvasMouseDown(e: MouseEvent): void {
    if (e.button !== 0) {
      return;
    }

    if (!e.shiftKey && !e.ctrlKey) {
      this.clearSelection();
    }

    this.isPanning = true;
    this.panStartX = e.clientX - this.viewportX;
    this.panStartY = e.clientY - this.viewportY;
  }

  onRightClick(e: MouseEvent, node: GraphNode): void {
    e.preventDefault();
    e.stopPropagation();

    this.store.select(node);
    this.contextMenuX = e.clientX;
    this.contextMenuY = e.clientY;
    this.contextMenuVisible = true;
  }

  onGraphContextMenu(e: MouseEvent): void {
    e.preventDefault();
  }

  onConnectionClick(conn: Connection, e: MouseEvent): void {
    e.stopPropagation();

    const fromNode = this.store.nodeByUid(conn.fromUid!);
    const toNode = this.store.nodeByUid(conn.toUid!);

    if (!fromNode || !toNode) {
      return;
    }

    this.openConnectionDetailsModal(conn, fromNode, toNode, this.resolveConnectionRows(conn, fromNode, toNode));
  }

  navigateNodes(direction: 'up' | 'down' | 'left' | 'right'): void {
    if (!this.selectedNode) {
      if (this.nodes.length > 0) {
        this.selectNode(this.nodes[0]);
      }
      return;
    }

    const [dx, dy] = NAVIGATION_STEPS[direction];
    const target = this.findNodeInDirection(this.selectedNode, dx, dy);

    if (target) {
      this.selectNode(target);
      this.centerOnNode(target);
    }
  }

  navigateUp(): void { this.navigateNodes('up'); }
  navigateDown(): void { this.navigateNodes('down'); }
  navigateLeft(): void { this.navigateNodes('left'); }
  navigateRight(): void { this.navigateNodes('right'); }

  /** Bound to Ctrl+F only to keep the browser's find bar from opening over the canvas. */
  focusSearch(): void {
  }

  deleteSelectedNodes(): void {
    this.store.removeSelected();
    this.refresh();
  }

  selectAsRootNode(): void {
    this.contextMenuVisible = false;
    const node = this.selectedNode;

    if (!node || node.id === this.rootNodeId) {
      return;
    }

    // The host navigates on this and re-binds rootNodeId, which reloads the graph.
    this.rootNodeSelected.emit(node.id);
  }

  setSelectedAsRoot(): void {
    if (this.selectedNode) {
      this.selectAsRootNode();
    }
  }

  toggleFocusMode(): void {
    this.focusMode = !this.focusMode;
    if (this.focusMode && this.selectedNode) {
      this.focusedNodeId = this.selectedNode.id;
      this.centerOnNode(this.selectedNode);
      return;
    }
    this.focusedNodeId = null;
  }

  focusOnSelected(): void {
    if (this.selectedNode) {
      this.toggleFocusMode();
    }
  }

  toggleMinimap(): void { this.showMinimap = !this.showMinimap; }

  toggleLegend(): void { this.showLegend = !this.showLegend; }
  toggleFilterBar(): void { this.showFilterBar = !this.showFilterBar; }

  /* ---------------------------------------------------- FILTERS ----------------------------------------------------- */

  applyFilters(): void {
    this.store.typesFilter = this.filterForm.value?.types || [];
    this.store.relationsFilter = this.filterForm.value?.relations || [];
    this.store.load(true);
    this.showFilterBar = false;
  }

  clearFilters(): void {
    this.filterForm.patchValue({ types: [], relations: [] });
    this.store.typesFilter = [];
    this.store.relationsFilter = [];
    this.store.load(true);
  }

  onScopeChange(patch: Partial<CiExplorerScope>): void { this.store.updateScope(patch); }

  hasActiveFilters(): boolean {
    return this.profileService.hasActiveFilters(this.store.typesFilter, this.store.relationsFilter);
  }

  switchFilterMode(mode: 'manual' | 'profile'): void {
    this.filterMode = mode;
    if (mode === 'profile') {
      this.loadProfiles();
    }
  }

  applyProfile(): void {
    const result = this.profileService.applyProfile(
      this.profiles,
      this.selectedProfileId,
      this.store.typesFilter,
      this.store.relationsFilter
    );

    this.store.typesFilter = result.typesFilter;
    this.store.relationsFilter = result.relationsFilter;
    this.store.load(true);
    this.showFilterBar = false;
  }

  /** The label belongs to the type, so the change lands on every node of it, on every level. */
  openLabelFieldModal(): void {
    this.contextMenuVisible = false;

    const node = this.selectedNode;
    const typeId = node?.ciNode?.type_info?.type_id;

    if (!this.canEdit || !typeId) {
      return;
    }

    const modalRef = this.fullscreenModalService.open(this.modalService, CiExplorerLabelModalComponent, {
      backdrop: 'static',
      windowClass: 'dg-modal-window',
      backdropClass: 'dg-modal-window-backdrop'
    });

    modalRef.componentInstance.typeId = typeId;
    modalRef.componentInstance.typeLabel = node.type;
    modalRef.componentInstance.sampleNode = node;

    modalRef.result.then(
      (fieldName: string | null) => {
        this.store.applyLabelField(typeId, fieldName ?? null);
        this.refresh();
      },
      () => undefined
    );
  }

  openProfileManager(): void {
    if (!this.canEdit) {
      return;
    }

    this.profileService.openProfileManager(
      this.modalService,
      this.typeOptionList,
      this.relationOptionList,
      () => this.loadProfiles()
    );
  }

  saveCurrentFiltersAsProfile(): void {
    if (!this.canEdit) {
      return;
    }

    this.profileService.saveCurrentFiltersAsProfile(
      this.modalService,
      this.typeOptionList,
      this.relationOptionList,
      this.store.typesFilter,
      this.store.relationsFilter,
      () => this.hasActiveFilters(),
      message => this.toastService.info(message)
    );
  }

  /* ------------------------------------------------ EXPORT / CHROME ------------------------------------------------- */

  exportGraphAsImage(): void {
    void this.exportService.exportGraphAsImage(this.canvas?.element.nativeElement, this.loaderService);
  }

  async toggleFullscreen(): Promise<void> {
    if (!document.fullscreenEnabled || !this.editorRoot?.nativeElement) {
      return;
    }

    try {
      if (this.isFullscreen && document.fullscreenElement) {
        await document.exitFullscreen();
        return;
      }
      await this.editorRoot.nativeElement.requestFullscreen();
    } catch {
      // Nothing useful to show the user; the view simply stays as it is.
    }
  }

  /* ------------------------------------------------- TEMPLATE AIDS -------------------------------------------------- */

  getNodeById(id: number): GraphNode | undefined { return this.store.nodeById(id); }

  /* ------------------------------------------------ PRIVATE FUNCTIONS ----------------------------------------------- */

  /** The canvas renders mutated node objects, so a repaint has to announce the move too. */
  private refresh(): void {
    this.store.tick();
    this.cdr.markForCheck();
  }

  private setupFormSubscriptions(): void {
    this.filterForm.get('types')!.valueChanges
      .pipe(takeUntil(this.destroy$))
      .subscribe(value => this.store.typesFilter = value || []);

    this.filterForm.get('relations')!.valueChanges
      .pipe(takeUntil(this.destroy$))
      .subscribe(value => this.store.relationsFilter = value || []);
  }

  private setupEventListeners(): void {
    fromEvent<KeyboardEvent>(document, 'keydown')
      .pipe(takeUntil(this.destroy$))
      .subscribe(event => this.handleKeyboard(event));

    fromEvent(window, 'resize')
      .pipe(debounceTime(300), takeUntil(this.destroy$))
      .subscribe(() => this.handleResize());

    fromEvent(document, 'fullscreenchange')
      .pipe(takeUntil(this.destroy$))
      .subscribe(() => this.onFullscreenChange());

    fromEvent<MouseEvent>(document, 'mousemove')
      .pipe(takeUntil(this.destroy$))
      .subscribe(event => this.onDocumentMouseMove(event));

    fromEvent(document, 'mouseup')
      .pipe(takeUntil(this.destroy$))
      .subscribe(() => this.onDocumentMouseUp());

    fromEvent<MouseEvent>(document, 'click')
      .pipe(takeUntil(this.destroy$))
      .subscribe(event => this.onDocumentClick(event));
  }

  private handleKeyboard(event: KeyboardEvent): void {
    if (this.isTypingElsewhere(event)) {
      return;
    }

    const action = KEYBOARD_SHORTCUTS[this.keyCombo(event) as keyof typeof KEYBOARD_SHORTCUTS];

    if (action) {
      event.preventDefault();
      this.keyboardActions[action]();
    }
    this.refresh();
  }

  /**
   * Canvas shortcuts stay on the canvas.
   *
   * They are bound to the document, so without this an open modal would lose Enter to
   * `preventDefault` and never activate its own buttons.
   */
  private isTypingElsewhere(event: KeyboardEvent): boolean {
    const target = event.target as Element | null;
    return !!target?.closest?.('input, textarea, select, [contenteditable="true"], ngb-modal-window');
  }

  /** Spelling has to match the combos used as keys in KEYBOARD_SHORTCUTS. */
  private keyCombo(event: KeyboardEvent): string {
    const parts: string[] = [];

    if (event.ctrlKey || event.metaKey) {
      parts.push('Ctrl');
    }
    if (event.shiftKey) {
      parts.push('Shift');
    }
    if (event.altKey) {
      parts.push('Alt');
    }
    parts.push(event.key === '+' ? 'Plus' : event.key === '-' ? 'Minus' : event.key);

    return parts.join('+');
  }

  /** Only the pan path does work here, so an idle pointer never reaches change detection. */
  private onDocumentMouseMove(e: MouseEvent): void {
    if (!this.isPanning) {
      return;
    }
    this.graphViewport.setViewport(e.clientX - this.panStartX, e.clientY - this.panStartY);
    this.cdr.markForCheck();
  }

  private onDocumentMouseUp(): void {
    if (!this.isDragging && !this.isPanning && !this.isMultiSelecting) {
      return;
    }
    this.isDragging = false;
    this.isPanning = false;
    this.isMultiSelecting = false;
    this.refresh();
  }

  private onDocumentClick(e: MouseEvent): void {
    if (!this.contextMenuVisible || (e.target as Element)?.closest('.context-menu')) {
      return;
    }
    this.contextMenuVisible = false;
    this.cdr.markForCheck();
  }

  private handleResize(): void {
    this.centerViewport();
    this.refresh();
  }

  private onFullscreenChange(): void {
    this.isFullscreen = document.fullscreenElement === this.editorRoot?.nativeElement;
    this.handleResize();
  }

  private findNodeInDirection(from: GraphNode, dx: number, dy: number): GraphNode | undefined {
    const candidates = this.nodes.filter(n => n.id !== from.id);
    const closestTo = (pool: GraphNode[]): GraphNode | undefined => pool.length
      ? pool.reduce((closest, node) =>
        Math.abs(node.x - from.x) < Math.abs(closest.x - from.x) ? node : closest)
      : undefined;

    if (dy !== 0) {
      return closestTo(candidates.filter(n => n.level === from.level + dy));
    }

    const sameLevel = candidates.filter(n => n.level === from.level);
    return closestTo(sameLevel.filter(n => dx > 0 ? n.x > from.x : n.x < from.x));
  }

  private loadFilterOptions(): void {
    this.profileService.loadFilterOptions(this.typeService, this.relationService, this.loaderService)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: result => {
          this.typeOptionList = result.types;
          this.relationOptionList = result.relations;
          this.cdr.markForCheck();
        },
        error: err => this.toastService.error(err?.error?.message || 'Could not load the filter options.')
      });
  }

  private loadProfiles(): void {
    this.loaderService.show();
    this.profileService.getProfiles()
      .pipe(finalize(() => this.loaderService.hide()), takeUntil(this.destroy$))
      .subscribe({
        next: profiles => {
          this.store.profiles = profiles;
          this.cdr.markForCheck();
        },
        error: err => this.toastService.error(err?.error?.message || 'Could not load the filter profiles.')
      });
  }

  private openNodeDetailsModal(node: GraphNode): void {
    const modalRef = this.fullscreenModalService.open(this.modalService, NodeDetailsModalComponent, {
      size: 'xl',
      backdrop: 'static',
      scrollable: true,
      windowClass: 'dg-modal-window',
      backdropClass: 'dg-modal-window-backdrop'
    });

    modalRef.componentInstance.loadNode(node);
    modalRef.componentInstance.nodeTypeConfigs = this.store.nodeTypeConfigs;
    modalRef.result.catch(() => undefined);
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

  private openConnectionDetailsModal(
    conn: Connection,
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
    modalRef.componentInstance.direction = resolveDirection(fromNode, toNode, conn);
  }
}
