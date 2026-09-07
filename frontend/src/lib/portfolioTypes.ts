// W4 PR-B — portfolio surfaces contract types.
// Mirrors auth/reports.py portfolio payloads (PR-A, main 20e8e24).
//
// PDPO notes carried over from the backend schema:
//  - full student ids never appear on these payloads (mask prefix only)
//  - share_card is the whitelist-only serialization contract (R3); the
//    frontend must never invent additional card fields.
//  - competencies_4d badge values are rendered verbatim (R5: no client-side
//    label translation).

/** 4D badge values — backend vocabulary, render verbatim (never translate). */
export type FourDKey = 'dream' | 'discover' | 'design' | 'deliver';

/** One portfolio item (shared item view used by both surfaces). */
export interface PortfolioItem {
  item_id: string;
  topic_id: string;
  subject: string;
  title: string;
  description: string;
  evidence_excerpt: string;
  competencies_4d: string[];
  growth_note: string; // backend text (improvement / consistent / keep-going)
  kid_label: string;
  achieved_at: string;
  linked_project_id: string | null;
}

/** GET /api/student/portfolio — kid-facing surface (no share_card, R2). */
export interface KidPortfolioResponse {
  items: PortfolioItem[];
  empty: boolean;
}

/** Whitelist-only share_card payload (R3) — rendered as-is by the card. */
export interface ShareCard {
  display_name: string; // first name only (B24 / R6)
  item_id: string;
  title: string;
  artifact_summary: string;
  competencies_4d: string[];
  kid_label: string;
  brand: string;
  generated_at: string;
}

export interface ParentPortfolioStudent {
  student_id: string; // 8-char mask prefix
  display_name: string;
  age_band: string;
  lang_code: string;
  media_consent: string;
}

/** GET /api/parent/portfolio/{student_id} — items + parallel share_cards. */
export interface ParentPortfolioResponse {
  student: ParentPortfolioStudent;
  items: PortfolioItem[];
  share_cards: ShareCard[];
  empty: boolean;
}
