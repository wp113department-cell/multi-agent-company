/**
 * G13 (2026-10-16): links built from stored data (a pull-request URL, …)
 * open only as http(s). A `javascript:` or `data:` URL would run code in the
 * app's origin when clicked; the production CSP blocks it too, this is the
 * second line of defence.
 */
export function safeExternalUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.toString() : null;
  } catch {
    return null;
  }
}
