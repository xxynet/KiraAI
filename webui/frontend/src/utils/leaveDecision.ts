/**
 * Pure pieces of the configuration page's "leave with unsaved edits" flow.
 * Kept Vue-free so the navigation policy and the one-shot decision gate can be
 * unit tested from plain Node (see tests/leaveDecision.test.mjs).
 */

export interface LeaveRequest {
  /** Route the user is trying to open. */
  targetFullPath: string
  /** Route currently displayed. */
  currentFullPath: string
  /** Number of edited fields that are not saved yet. */
  unsavedChanges: number
  /** Route name of the target, when it has one (vue-router allows symbols too). */
  targetName?: string | symbol | null
  /** Route names that must never be blocked, e.g. the auth screens. */
  allowedNames?: readonly (string | symbol)[]
}

/**
 * Whether the navigation needs a user decision.
 *
 * Query-only changes count: the layout keys its view component by full path, so
 * "/configuration?tab=models" to "/configuration" remounts the page and drops
 * the edits even though the route record stays the same.
 */
export function needsLeaveDecision(request: LeaveRequest): boolean {
  if (request.unsavedChanges <= 0) return false
  if (request.targetFullPath === request.currentFullPath) return false
  if (request.targetName && request.allowedNames?.includes(request.targetName)) return false
  return true
}

export interface LeaveGate {
  /** True while a navigation is waiting for the user's answer. */
  readonly pending: boolean
  /**
   * Hold a navigation until it is settled. A navigation that was already waiting
   * is settled with `false`, so two prompts can never stack up.
   */
  wait(): Promise<boolean>
  /**
   * Answer the waiting navigation. Returns false when nothing was waiting, which
   * is how a stale answer (e.g. a save that finishes after the user stayed) is
   * ignored instead of navigating behind the user's back.
   */
  settle(leave: boolean): boolean
}

export function createLeaveGate(): LeaveGate {
  let resolvePending: ((leave: boolean) => void) | null = null

  return {
    get pending(): boolean {
      return resolvePending !== null
    },
    wait(): Promise<boolean> {
      const previous = resolvePending
      resolvePending = null
      previous?.(false)
      return new Promise<boolean>((resolve) => {
        resolvePending = resolve
      })
    },
    settle(leave: boolean): boolean {
      const resolve = resolvePending
      resolvePending = null
      if (!resolve) return false
      resolve(leave)
      return true
    },
  }
}
