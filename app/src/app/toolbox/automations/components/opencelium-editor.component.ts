import * as ReactDOM from 'react-dom';
import React from 'react';
import {
  Component,
  ElementRef,
  Input,
  Output,
  EventEmitter,
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
  @Output() connectionChange = new EventEmitter<any>();
  @Output() saveConnection = new EventEmitter<any>();

  private container?: HTMLElement;
  private ConnectionEditor?: any;

  constructor(private host: ElementRef) {}

  async ngAfterViewInit() {
    this.ConnectionEditor = ConnectionEditor;
    this.container = this.host.nativeElement.querySelector('div');
    this.render();
  }

  /** Re-render when inputs change */
  ngOnChanges(changes: SimpleChanges) {
    
    // Object.keys(changes).forEach(key => {
    //   const change = changes[key];
    //   console.log(`  - ${key}:`, {
    //     previousValue: change.previousValue,
    //     currentValue: change.currentValue,
    //     firstChange: change.firstChange
    //   });
    // });

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
      onChange: (connection: any) => {
        this.connectionChange.emit(connection);
      },
      saveConnection: async (connection: any) => {
        this.saveConnection.emit(connection);
      }
    };

    // Only send connector IDs in create mode
    if (!this.initConnection) {
      props.sourceConnectorId = this.sourceConnectorId;
      props.targetConnectorId = this.targetConnectorId;
    } 

    ReactDOM.render(
      React.createElement(this.ConnectionEditor, props),
      this.container
    );

  }
}
