import * as ReactDOM from 'react-dom';
import React from 'react';
import {
  Component,
  ElementRef,
  Input,
  AfterViewInit,
  OnChanges,
  OnDestroy,
  SimpleChanges,
  Output,
  EventEmitter,
} from '@angular/core';
@Component({
  selector: 'opencelium-log-viewer',
  standalone: true,
  template: `<div class="react-scope"></div>`,
})
export class OpenCeliumLogsViewComponent
  implements AfterViewInit, OnChanges, OnDestroy
{
  @Input() baseUrl = '';
  @Input() token = '';
  @Input() executionId: string | number = '';
  @Output() logViewLoad = new EventEmitter<void>();

  private container?: HTMLElement;
  private LogsView?: any;

  constructor(private host: ElementRef) {}
  async ngAfterViewInit() {

    // this.LogsView = LogsView;
    this.container = this.host.nativeElement.querySelector('div');
    this.integrateStyles();
    this.render();
    try {
        await this.loadLogsView();
        this.render();
      } catch (error) {
        console.error('Failed to load OpenCelium logs view', error);
      }
  }


  /** Re-render when inputs change */
  ngOnChanges(changes: SimpleChanges) {
    if (this.container && this.LogsView) {
      this.render();
    }
  }

  /** Unmount React when Angular destroys the component */
  ngOnDestroy() {
    if (this.container) {
      ReactDOM.unmountComponentAtNode(this.container);
    }
    this.removeStyles();
  }

  private integrateStyles() {
    const stylePaths = [
      'assets/logs-view/logs-view.css',
      'assets/logs-view/fonts/fonts.css',
    ];

    // Load each file once
    stylePaths.forEach((path, index) => {
      const id = `logs-view-style-${index}`;

      if (!document.getElementById(id)) {
        const link = document.createElement('link');
        link.id = id;
        link.rel = 'stylesheet';
        link.href = path;

        document.head.appendChild(link);
      }
    });
  }

  private removeStyles() {
    const styleCount = 2;

    for (let index = 0; index < styleCount; index += 1) {
      const id = `logs-view-style-${index}`;
      const element = document.getElementById(id);

      if (element) {
        element.remove();
      }
    }
  }

  /** Mount or re-render the React component */
  private render() {
    if (!this.container || !this.LogsView) return;

    const baseUrl = this.baseUrl;
    const executionId = Number(this.executionId || 0);

    ReactDOM.render(
      React.createElement(this.LogsView, {
        baseUrl,
        token: this.token,
        executionId,
        onLoad: () => {
          this.logViewLoad.emit();
        }
      }),
      this.container
    );
  }

  private async loadLogsView(): Promise<void> {
    if (this.LogsView) {
      return;
    }
    const module = await import('../../../../assets/logs-view/logs-view.js');
    this.LogsView = module?.default || module;
  }

}
