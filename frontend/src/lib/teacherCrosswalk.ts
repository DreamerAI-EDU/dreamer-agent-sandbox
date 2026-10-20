// PR-5 A6 — the teacher-only crosswalk one-pager (design book §6), verbatim.
//
// 施工令 PR-5 §三: "crosswalk（§6）：九行全表逐字拷贝，含「即係國際課程講嘅
// 創意思維…」等广东话口头桥，一个标点都不许动。"
//
// This module is the ONLY place those nine rows live in the front end. The
// anchor test (tests/test_pr5_frozen_copy_anchor.py) compares every cell below
// character-for-character against §6 of the signed design book v1.1.
//
// 红线 (§5.4 / §B4): this file is rendered EXCLUSIVELY on /teacher/crosswalk
// (teacher role). Its text contains the internal framework names on purpose —
// grep gate T-5 asserts none of it ever appears in a parent route response.

/** §6 chapter heading (verbatim, markdown prefix included). */
export const CROSSWALK_SECTION_HEADING = "## 第 6 章　老师 crosswalk 一页纸（内部专用，永不出家长版）";

/** Display title for the on-screen page — the heading text without "## ". */
export const CROSSWALK_TITLE = "老师 crosswalk 一页纸（内部专用，永不出家长版）";

/** §6 table purpose line (verbatim). */
export const CROSSWALK_PURPOSE = "用途：老师口头向家长解释评分依据的统一口径；印一张过胶贴住工位即可。";

/** §6 column heads (verbatim, in book order). */
export const CROSSWALK_COLUMNS = {
  parentSees: "家长版见到",
  internal: "内部对应（IB ATL）",
  oralBridge: "口头桥示例（广东话）",
} as const;

export interface CrosswalkRow {
  /** 家长版见到 */
  readonly parentSees: string;
  /** 内部对应（IB ATL） */
  readonly internal: string;
  /** 口头桥示例（广东话） */
  readonly oralBridge: string;
}

/** §6 nine rows, book order, verbatim. */
export const CROSSWALK_ROWS: readonly CrosswalkRow[] = [
  {
    parentSees: "Dream（想象）",
    internal: "Thinking Skills — Creative Thinking",
    oralBridge: "「即係國際課程講嘅創意思維——我哋睇佢作品有幾原創。」",
  },
  {
    parentSees: "Discover（探究）",
    internal: "Research ＋ Critical Thinking",
    oralBridge: "「即係資訊素養同事實查核——佢識唔識『先查證再信』。」",
  },
  {
    parentSees: "Design（创造）",
    internal: "Communication — Literacy ＋ 執行力",
    oralBridge: "「即係將諗法變成成品嘅能力，仲要識改到更好。」",
  },
  {
    parentSees: "Deliver（分享）",
    internal: "Communication — Exchanging Information",
    oralBridge: "「即係口頭表達同台上自信。」",
  },
  {
    parentSees: "等级 3 Exemplary",
    internal: "超出年级期望",
    oralBridge: "「佢做嘅嘢已經超越呢個年級嘅要求。」",
  },
  {
    parentSees: "等级 2 Achieved",
    internal: "达到年级期望",
    oralBridge: "「佢穩穩陣陣達到咗要求。」",
  },
  {
    parentSees: "等级 1 Developing",
    internal: "发展中，需要支架",
    oralBridge: "「佢喺路上，仲需要多啲扶一扶。」",
  },
  {
    parentSees: "等级 0 Not Yet",
    internal: "尚未展现（非批评）",
    oralBridge: "「唔係佢差，係呢項未開始評——下階段先係重頭。」",
  },
  {
    parentSees: "Learner Profile 亮点",
    internal: "IB Learner Profile",
    oralBridge: "「國際課程會叫呢啲做學習者特質，我哋報告用返自己嘅小朋友语言。」",
  },
];

/** §6 closing standard answer (verbatim, one line in the book). */
export const CROSSWALK_STANDARD_ANSWER = "若家长直接问「系咪 IB 嗰套？」标准答案：「我哋把尺同國際課程嘅能力框架對齊，但用 Dreamer 自己嘅语言同作品证据嚟呈现，等家长唔使读教育学都睇得明。」";
