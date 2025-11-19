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
} from '@angular/core';
import ConnectionEditor from './opencelium-editor/connection-editor.js';

@Component({
  selector: 'opencelium-editor',
  standalone: false,
  template: `<div></div>`,
})
export class OpenCeliumEditorComponent
  implements AfterViewInit, OnChanges, OnDestroy
{
  @Input() token = '';
  @Input() sourceConnectorId = '';
  @Input() targetConnectorId = '';
  @Input() templates: any[] = [];
  @Input() connectors: any[] = [];
  @Input() invokers: any[] = [];

  private container?: HTMLElement;
  private ConnectionEditor?: any;

  constructor(private host: ElementRef) {}

  async ngAfterViewInit() {
    console.log(' OpenCelium Editor Component - Initializing...');
    console.log(' Input Data Summary:');
    console.log('  - Token:', this.token ? ' Present (masked)' : 'Missing');
    console.log('  - Source Connector ID:', this.sourceConnectorId || ' Empty');
    console.log('  - Target Connector ID:', this.targetConnectorId || ' Empty');
    console.log('  - Templates:', `Array(${this.templates.length})`, this.templates);
    console.log('  - Connectors:', `Array(${this.connectors.length})`, this.connectors);
    console.log('  - Invokers:', `Array(${this.invokers.length})`, this.invokers);

    this.ConnectionEditor = ConnectionEditor;
    this.container = this.host.nativeElement.querySelector('div');
    this.render();
  }

  /** Re-render when inputs change */
  ngOnChanges(changes: SimpleChanges) {
    console.log('OpenCelium Editor Component - Input Changes Detected:');
    
    Object.keys(changes).forEach(key => {
      const change = changes[key];
      console.log(`  - ${key}:`, {
        previousValue: change.previousValue,
        currentValue: change.currentValue,
        firstChange: change.firstChange
      });
    });

    if (this.container && this.ConnectionEditor) {
      this.render();
    }
  }

  /** Unmount React when Angular destroys the component */
  ngOnDestroy() {
    if (this.container) {
      ReactDOM.unmountComponentAtNode(this.container);
    }
  }

  /** Mount or re-render the React component */
  private render() {
    if (!this.container || !this.ConnectionEditor) {
      return;
    }

    console.log('OpenCelium Editor - Rendering React Component with Data:');
    console.log('  - Token:', this.token );
    console.log('  - Source Connector ID:', this.sourceConnectorId || ' Empty');
    console.log('  - Target Connector ID:', this.targetConnectorId || ' Empty');
    console.log('  - Templates:', this.templates);
    console.log('  - Connectors Count:', this.connectors);
    console.log('  - Invokers Count:', this.invokers);
    console.log('  - Full Data Being Passed to React:', {
      token: this.token ,
      sourceConnectorId: this.sourceConnectorId,
      targetConnectorId: this.targetConnectorId,
      template: this.templates,
      connectors: this.connectors,
      invokers: this.invokers
    });

    ReactDOM.render(
      React.createElement(this.ConnectionEditor, {
        token: this.token,
        sourceConnectorId: this.sourceConnectorId,
        targetConnectorId: this.targetConnectorId,
        template: this.templates,
        connectors: this.connectors,
        invokers: this.invokers,
        onChange: (data: any) => {console.log(' OpenCelium Editor - onChange event:', data); }
      }),
      this.container
    );

    console.log(' OpenCelium Editor - React Component Rendered Successfully');
  }
}
