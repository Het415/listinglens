/**
 * Helpers for cancelling in-flight requests when the selected product changes.
 *
 * Every ASIN-keyed loader in the dashboard follows the same shape: an effect
 * keyed on `asin` that fetches, then guards its `setState` calls with a
 * `cancelled` closure flag. That flag stops *stale state* from landing, but it
 * does not stop the *request* — the browser keeps the connection open and the
 * backend keeps working. Pairing each effect with an `AbortController` closes
 * that gap; `cancelled` is still needed so the resulting rejection doesn't get
 * rendered as a user-facing error.
 */

/**
 * True when a rejection is the deliberate `controller.abort()` from an effect
 * cleanup rather than a real failure. Such rejections must be swallowed: the
 * component is either unmounting or already loading a different ASIN, so
 * surfacing "Failed to load" would be both wrong and visible.
 *
 * `fetch` rejects with a `DOMException` named `AbortError`, but a caller may
 * also abort with a custom reason, so the check is on the name rather than the
 * constructor.
 */
export function isAbortError(err: unknown): boolean {
  return err instanceof Error && err.name === 'AbortError'
}
