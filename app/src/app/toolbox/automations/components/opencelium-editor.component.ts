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
  @Input() template: any = null;
  @Input() connectors: any[] = [];
  @Input() invokers: any[] = [];
  @Input() initConnection: any = null;

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

    // Always send these properties
    const props: any = {
      token: this.token,
      templates: this.templates,
      template: this.template,
      initConnection: this.initConnection,
      connectors: this.connectors,
      invokers: this.invokers,
      onChange: (data: any) => {console.log('connection onChange', data)}
    };

    // Only send connector IDs in create mode
    if (!this.initConnection) {
      props.sourceConnectorId = this.sourceConnectorId;
      props.targetConnectorId = this.targetConnectorId;
      console.log('  - Mode: CREATE - Sending connector IDs');
    } else {
      console.log('  - Mode: EDIT - Not sending connector IDs');
    }

    console.log('  - Final Props Being Passed to React:', props);

    ReactDOM.render(
      React.createElement(this.ConnectionEditor, props),
      this.container
    );

  }
}
