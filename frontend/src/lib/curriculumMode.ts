// PR-D-c2 §2 — the client ↔ relay course-mode contract, stated in ONE place.
//
// The rare-and-shared thing (a frame key that both sides must agree on) gets a
// module of its own so the Welcome button, the chat page and the frame builder
// can never drift apart — the same habit the B26 lang-code guard exists for.
//
// The relay half lives in auth/ws_chat.py (_CURRICULUM_MODE_FLAG /
// _CURRICULUM_MODE_VALUE); the pair is pinned by
// tests/test_pr_d_c2_curriculum_button.py. Changing either side is a frame
// contract change and needs gate approval (PR-D-c2 scope §8).

/** Top-level frame key. Never nested: the engine's layer is extra="forbid"
 *  and would reject the whole turn (F-2, verified in PR-D-c1). */
export const DIBI_MODE_FLAG = 'dibi_mode';

/** The only whitelisted value. v1 says *that* the child is in course mode —
 *  never which week, which slug or which student (HC-c2-1 / HC-c2-2: the
 *  week is the server's to decide, the client never guesses it). */
export const DIBI_MODE_CURRICULUM = 'curriculum';

/** /chat query param that arms course mode for this visit. It carries UI mode
 *  only — no week / slug / student id ever rides a URL. */
export const CURRICULUM_MODE_QUERY = 'mode';

/** True only for the exact whitelisted value: no coercion, no guessing. */
export function isCurriculumModeParam(value: string | null | undefined): boolean {
  return value === DIBI_MODE_CURRICULUM;
}
