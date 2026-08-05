import { Directive, HostListener, Input, OnDestroy, Renderer2 } from '@angular/core';

@Directive({
  selector: '[dgHorizontalResize]',
  standalone: true
})
export class HorizontalResizeDirective implements OnDestroy {
  @Input('dgHorizontalResize') resizeContainer?: HTMLElement;
  @Input() dgResizeCssVar = '--content-width';
  @Input() dgResizeMin = 320;
  @Input() dgResizeMax = 920;
  @Input() dgResizeMinOpposite = 0;
  @Input() dgResizeAnchor: 'left' | 'right' = 'right';
  @Input() dgResizeActiveClass = 'is-resizing';

  private isResizing = false;
  private removeMouseMove?: () => void;
  private removeMouseUp?: () => void;
  private removeTouchMove?: () => void;
  private removeTouchEnd?: () => void;

  constructor(private renderer: Renderer2) {}

  ngOnDestroy(): void {
    this.endResize();
  }

  @HostListener('mousedown', ['$event'])
  onMouseDown(event: MouseEvent): void {
    this.startResize(event);
  }

  @HostListener('touchstart', ['$event'])
  onTouchStart(event: TouchEvent): void {
    this.startResize(event);
  }

  private startResize(event: MouseEvent | TouchEvent): void {
    if (!this.resizeContainer || this.isResizing) return;
    event.preventDefault();
    this.isResizing = true;
    this.resizeContainer.classList.add(this.dgResizeActiveClass);
    this.bindDocumentListeners();
  }

  private bindDocumentListeners(): void {
    if (this.removeMouseMove) return;
    this.removeMouseMove = this.renderer.listen('document', 'mousemove', (event: MouseEvent) => {
      if (!this.isResizing) return;
      this.updateWidth(event.clientX);
    });
    this.removeMouseUp = this.renderer.listen('document', 'mouseup', () => this.endResize());
    this.removeTouchMove = this.renderer.listen('document', 'touchmove', (event: TouchEvent) => {
      if (!this.isResizing || event.touches.length === 0) return;
      this.updateWidth(event.touches[0].clientX);
    });
    this.removeTouchEnd = this.renderer.listen('document', 'touchend', () => this.endResize());
  }

  private updateWidth(clientX: number): void {
    if (!this.resizeContainer) return;
    const rect = this.resizeContainer.getBoundingClientRect();
    const rawWidth = this.dgResizeAnchor === 'right'
      ? rect.right - clientX
      : clientX - rect.left;
    const maxAllowed = Math.max(
      this.dgResizeMin,
      Math.min(this.dgResizeMax, rect.width - this.dgResizeMinOpposite)
    );
    const clamped = Math.max(this.dgResizeMin, Math.min(maxAllowed, rawWidth));
    this.resizeContainer.style.setProperty(this.dgResizeCssVar, `${clamped}px`);
  }

  private endResize(): void {
    if (!this.isResizing) return;
    this.isResizing = false;
    this.resizeContainer?.classList.remove(this.dgResizeActiveClass);
    this.removeMouseMove?.();
    this.removeMouseUp?.();
    this.removeTouchMove?.();
    this.removeTouchEnd?.();
    this.removeMouseMove = undefined;
    this.removeMouseUp = undefined;
    this.removeTouchMove = undefined;
    this.removeTouchEnd = undefined;
  }
}
