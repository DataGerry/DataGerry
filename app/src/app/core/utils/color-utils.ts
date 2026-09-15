/**
 * Determines whether black or white text is more readable on a given background color.
 * @param hexColor The background color in hex format (e.g., #RRGGBB).
 * @returns 'black' or 'white' depending on the contrast.
 */
export function getTextColorBasedOnBackground(hexColor: string): string {
    // Remove the hash if present
    hexColor = hexColor?.replace('#', '');
  
    // Convert hex to RGB
    const r = parseInt(hexColor?.substring(0, 2), 16);
    const g = parseInt(hexColor?.substring(2, 4), 16);
    const b = parseInt(hexColor?.substring(4, 6), 16);
  
    // Calculate luminance
    const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  
    // Return black for light backgrounds and white for dark backgrounds
    return luminance > 0.5 ? 'black' : 'white';
  }


  export function hexToRgb(hex: string): [number, number, number] {
    if (!hex?.startsWith('#')) return [119, 119, 119];  // fallback grey
    const bigint = parseInt(hex?.substring(1), 16);
    const r = (bigint >> 16) & 255;
    const g = (bigint >> 8) & 255;
    const b = bigint & 255;
    return [r, g, b];
  }

  const HEX_COLOR_PATTERN = /^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i;

  /**
   * Validates a hex color coming from the backend and expands the short form to #RRGGBB.
   * @returns The normalized color, or null when the value is not a plain hex color.
   */
  export function normalizeHexColor(value: string | null | undefined): string | null {
    const hex = value?.trim().toLowerCase();

    if (!hex || !HEX_COLOR_PATTERN.test(hex)) {
      return null;
    }

    return hex.length === 4 ? `#${hex[1]}${hex[1]}${hex[2]}${hex[2]}${hex[3]}${hex[3]}` : hex;
  }

  export interface Hsl {
    hue: number;        // 0-360
    saturation: number; // 0-100
    lightness: number;  // 0-100
  }

  const NEUTRAL_HSL: Hsl = { hue: 0, saturation: 0, lightness: 50 };

  /**
   * Reads a hex colour as HSL so it can be edited channel by channel.
   * Anything that is not a hex literal (a CSS name, an empty field) starts from a neutral grey.
   */
  export function hexToHsl(value: string | null | undefined): Hsl {
    const hex = normalizeHexColor(value);

    if (!hex) {
      return { ...NEUTRAL_HSL };
    }

    const [red, green, blue] = hexToRgb(hex).map((channel) => channel / 255);
    const max = Math.max(red, green, blue);
    const min = Math.min(red, green, blue);
    const lightness = (max + min) / 2;
    const delta = max - min;

    if (delta === 0) {
      return { hue: 0, saturation: 0, lightness: Math.round(lightness * 100) };
    }

    const hue = max === red
      ? 60 * (((green - blue) / delta + 6) % 6)
      : max === green
        ? 60 * ((blue - red) / delta + 2)
        : 60 * ((red - green) / delta + 4);

    return {
      hue: Math.round(hue),
      saturation: Math.round((delta / (1 - Math.abs(2 * lightness - 1))) * 100),
      lightness: Math.round(lightness * 100)
    };
  }

  /** HSL back to the #rrggbb literal the field stores. */
  export function hslToHex({ hue, saturation, lightness }: Hsl): string {
    const angle = ((hue % 360) + 360) % 360;
    const sat = clampPercent(saturation) / 100;
    const light = clampPercent(lightness) / 100;
    const chroma = (1 - Math.abs(2 * light - 1)) * sat;
    const second = chroma * (1 - Math.abs(((angle / 60) % 2) - 1));
    const base = light - chroma / 2;
    const sectors: readonly [number, number, number][] = [
      [chroma, second, 0], [second, chroma, 0], [0, chroma, second],
      [0, second, chroma], [second, 0, chroma], [chroma, 0, second]
    ];

    return '#' + sectors[Math.floor(angle / 60) % 6]
      .map((channel) => Math.round((channel + base) * 255).toString(16).padStart(2, '0'))
      .join('');
  }

  function clampPercent(value: number): number {
    return Math.min(100, Math.max(0, value));
  }
