import {
  Directive,
  ElementRef,
  EventEmitter,
  Input,
  OnDestroy,
  Output,
  Renderer2,
  inject
} from '@angular/core';

/**
 * Toggles the native Fullscreen API on a target element and reports the state.
 *
 * Apply it to the element that should fill the screen and drive it through the
 * exported reference:
 *
 *   <section dgFullscreen #fs="dgFullscreen" (fullscreenChange)="onChange($event)">
 *     <button (click)="fs.toggle()">…</button>
 *   </section>
 *
 * The host element goes fullscreen by default; pass an explicit element to the
 * input to target a different one. The reported state stays in sync with browser
 * driven changes such as pressing Escape.
 */
@Directive({
  selector: '[dgFullscreen]',
  standalone: true,
  exportAs: 'dgFullscreen'
})
export class FullscreenDirective implements OnDestroy {
  @Input('dgFullscreen') target?: HTMLElement | '';

  @Output() fullscreenChange = new EventEmitter<boolean>();

  private readonly hostRef = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly renderer = inject(Renderer2);
  private readonly removeChangeListener: () => void;

  private active = false;

  constructor() {
    this.removeChangeListener = this.renderer.listen('document', 'fullscreenchange', () => this.syncState());
  }

  ngOnDestroy(): void {
    this.removeChangeListener?.();
  }

  get isFullscreen(): boolean {
    return this.active;
  }

  async toggle(): Promise<void> {
    if (this.active) {
      await this.exit();
    } else {
      await this.enter();
    }
  }

  async enter(): Promise<void> {
    const element = this.fullscreenElement;
    if (!document.fullscreenEnabled || !element?.requestFullscreen) {
      return;
    }
    try {
      await element.requestFullscreen();
    } catch {
      // A blocked request leaves the state untouched; fullscreenchange stays authoritative.
    }
  }

  async exit(): Promise<void> {
    if (!document.fullscreenElement) {
      return;
    }
    try {
      await document.exitFullscreen();
    } catch {
      // Ignore; fullscreenchange keeps the reported state consistent.
    }
  }

  private get fullscreenElement(): HTMLElement {
    return this.target instanceof HTMLElement ? this.target : this.hostRef.nativeElement;
  }

  private syncState(): void {
    const active = document.fullscreenElement === this.fullscreenElement;
    if (active !== this.active) {
      this.active = active;
      this.fullscreenChange.emit(active);
    }
  }
}
