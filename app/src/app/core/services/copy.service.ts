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
import { inject, Injectable } from '@angular/core';
import { ToastService } from 'src/app/layout/toast/toast.service';

@Injectable({
  providedIn: 'root'
})
export class CopyService {

  private toastService = inject(ToastService);

  /**
   * Copy text to clipboard using modern Clipboard API with fallback
   * @param text The text to copy to clipboard
   * @returns Promise that resolves to true if successful, false otherwise
   */
  public async copyToClipboard(text: string): Promise<boolean> {
    if (!text || text.trim() === '') {
      return false;
    }

    //  modern Clipboard API first
    if (navigator.clipboard && window.isSecureContext) {
      try {
        await navigator.clipboard.writeText(text);
        return true;
      } catch (err) {
        return this.copyToClipboardLegacy(text);
      }
    } else {
      // Fallback for older browsers or insecure contexts
      return this.copyToClipboardLegacy(text);
    }
  }

  /**
   * Copy text to clipboard with automatic feedback
   * @param text The text to copy to clipboard
   * @param context Context for the copy operation 
   * @returns Promise that resolves to true if successful, false otherwise
   */
  public async copyWithFeedback(text: string, context: string = 'identifier'): Promise<boolean> {
    if (!text || text.trim() === '') {
      return false;
    }

    const success = await this.copyToClipboard(text);
    if (success) {
      this.toastService.info(`${context.charAt(0).toUpperCase() + context.slice(1)} copied to clipboard.`);
    } else {
      this.toastService.error(`Failed to copy ${context} to clipboard.`);
    }
    return success;
  }

  /**
   * Legacy method for copying text to clipboard
   * @param text The text to copy to clipboard
   * @returns boolean indicating success
   */
  private copyToClipboardLegacy(text: string): boolean {
    try {
      const textArea = document.createElement('textarea');
      textArea.value = text;
      textArea.style.position = 'fixed';
      textArea.style.left = '-999999px';
      textArea.style.top = '-999999px';
      document.body.appendChild(textArea);
      textArea.focus();
      textArea.select();
      
      const successful = document.execCommand('copy');
      document.body.removeChild(textArea);
      return successful;
    } catch (err) {
      return false;
    }
  }
}