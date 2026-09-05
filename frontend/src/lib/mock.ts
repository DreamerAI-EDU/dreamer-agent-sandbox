// Dreamer AI — 7-field JSON contract (mirrors Hermes chat response)
// NOTE: lang_code now includes 'zh-cn' (国语) — Hermes contract enum needs the same update.
export type Lang = 'en' | 'hk' | 'cn';

// cost_summary may arrive in either currency shape:
//   - HKD shape: the original Hermes mock contract
//   - USD shape: the real DeepTutor unified WS usage summary
//     {total_cost_usd, total_tokens, total_calls, prompt_tokens, completion_tokens}
//     read from result.metadata.metadata.cost_summary (nested) with a flat
//     result.metadata.cost_summary fallback — the render layer shows the
//     matching currency label and never invents an exchange rate.
export type CostSummaryHkd = {
  tokens_in: number;
  tokens_out: number;
  est_cost_hkd: number;
};

export type CostSummaryUsd = {
  total_tokens: number;
  total_calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_cost_usd: number;
};

export type CostSummary = CostSummaryHkd | CostSummaryUsd;

export interface ChatPayload {
  content: string;
  mode: 'DIRECT' | 'CONTEXTUAL' | 'HYBRID';
  lang_code: 'en' | 'zh-hk' | 'zh-cn';
  age_band: 'P1-P3' | 'P4-P6' | 'S1-S3';
  kid_label: string;
  citations: { kb: string; topic_id: string; title: string }[];
  cost_summary: CostSummary;
}

export interface BandTheme {
  band: ChatPayload['age_band'];
  label: string;
  accent: string;      // band identity colour
  bubble: string;      // assistant bubble tint (kept for future light surfaces)
  textScale: string;   // chat body size
  density: string;     // spacing scale
  mascot: string;
}

export const BAND_THEMES: BandTheme[] = [
  {
    band: 'P1-P3',
    label: 'P1–P3',
    accent: '#FF6B35',
    bubble: '#ffe4d6',
    textScale: 'text-xl leading-relaxed',
    density: 'space-y-6',
    mascot: 'Dibi',
  },
  {
    band: 'P4-P6',
    label: 'P4–P6',
    accent: '#83cef6',
    bubble: '#e3f3fd',
    textScale: 'text-lg leading-relaxed',
    density: 'space-y-5',
    mascot: 'Dibi',
  },
  {
    band: 'S1-S3',
    label: 'S1–S3',
    accent: '#ba9eff',
    bubble: '#efe9ff',
    textScale: 'text-base leading-relaxed',
    density: 'space-y-4',
    mascot: 'Dibi',
  },
];

export const MODE_BADGE: Record<ChatPayload['mode'], Record<Lang, string> & { color: string }> = {
  DIRECT: { en: 'Quick Answer', hk: '直接答', cn: '快速解答', color: '#e2fc91' },
  CONTEXTUAL: { en: 'Project Mode', hk: '專題模式', cn: '专题模式', color: '#83cef6' },
  HYBRID: { en: 'Answer + Project', hk: '答 + 專題', cn: '答 + 专题', color: '#ba9eff' },
};

export const LANG_CODE: Record<Lang, ChatPayload['lang_code']> = {
  en: 'en',
  hk: 'zh-hk',
  cn: 'zh-cn',
};

// Cost summary with no data — render layer must show "—" instead of a fake 0.
export const MOCK_NO_DATA_COST: ChatPayload['cost_summary'] = {
  tokens_in: 0,
  tokens_out: 0,
  est_cost_hkd: 0,
};

// ---- Mock scripted exchange (stands in for the real WS stream) ----

interface MockTurn {
  user: Record<Lang, string>;
  stages: { stage: string; note: Record<Lang, string> }[];
  payload: Record<ChatPayload['age_band'], Record<Lang, string>>;
  mode: ChatPayload['mode'];
  kid_label: string;
  citations: ChatPayload['citations'];
}

export const MOCK_TURNS: MockTurn[] = [
  {
    user: { en: 'What is a fraction?', hk: '分數係咩嚟㗎？', cn: '什么是分数？' },
    stages: [
      { stage: 'thinking', note: { en: 'Reading your question…', hk: '睇緊你條問題…', cn: '正在读你的问题…' } },
      { stage: 'retrieval', note: { en: 'Looking inside the Dreamer maths library…', hk: '喺 Dreamer 數學庫搵資料…', cn: '正在翻 Dreamer 数学库…' } },
      { stage: 'writing', note: { en: 'Writing an answer just for you…', hk: '寫緊一個專屬答案俾你…', cn: '正在为你写专属答案…' } },
    ],
    mode: 'DIRECT',
    kid_label: 'Maths Explorer',
    citations: [
      { kb: 'dreamer-maths-ai', topic_id: 'maths-fractions-01', title: 'Fractions — First Steps' },
    ],
    payload: {
      'P1-P3': {
        en: 'A fraction is a way to share things fairly! 🍕 If you cut a pizza into 4 equal pieces and eat 1, you ate **1/4** — one out of four. The bottom number says how many pieces there are. The top number says how many you took. Want to try drawing one with me?',
        hk: '分數就係公平分嘢嘅方法！🍕 如果你將一個薄餅切成 4 塊一樣大嘅件，食咗 1 件，你就食咗 **1/4**——四份入面嘅一份。下面嗰個數字話俾你知總共有幾多件，上面嗰個數字話俾你知你攞咗幾多件。想唔想同我一齊畫一個試下？',
        cn: '分数就是公平分东西的方法！🍕 如果你把一个披萨切成 4 块一样大的，吃掉 1 块，你就吃了 **1/4**——四份里面的一份。下面的数字告诉你一共有几块，上面的数字告诉你拿了几块。要不要跟我一起画一个试试？',
      },
      'P4-P6': {
        en: 'A fraction shows **part of a whole**. In 3/4, the denominator (bottom) tells you the whole is split into 4 equal parts, and the numerator (top) counts 3 of them. Fractions also live on the number line — 3/4 sits between 0 and 1. Try it: where does 1/2 sit compared to 3/4?',
        hk: '分數代表**整體嘅一部分**。喺 3/4 入面，分母（下面）話俾你知成個嘢分咗做 4 份一樣大嘅部分，分子（上面）就數咗其中 3 份。分數仲可以擺喺數線上面——3/4 就喺 0 同 1 之間。試下諗：1/2 同 3/4 邊個大啲？',
        cn: '分数表示**整体的一部分**。在 3/4 里，分母（下面）告诉你整体被分成 4 个相等的部分，分子（上面）数了其中 3 份。分数还可以放在数线上——3/4 就在 0 和 1 之间。试试看：1/2 和 3/4 哪个大？',
      },
      'S1-S3': {
        en: 'A fraction is a **ratio of two integers**, a/b where b ≠ 0. Three readings matter: part-whole (3 of 4 equal parts), division (3 ÷ 4 = 0.75), and a point on the number line. Being able to move between all three is what makes algebra with rational numbers feel easy later. Quick check: is 7/8 closer to 1 than 8/9 is?',
        hk: '分數係**兩個整數嘅比**，a/b 而 b ≠ 0。有三個睇法你要識：部分—整體（4 等份入面嘅 3 份）、除法（3 ÷ 4 = 0.75）、同埋數線上嘅一點。能夠喺三個睇法之間轉換，之後學有理數代數就會輕鬆好多。快問快答：7/8 定 8/9 接近 1 啲？',
        cn: '分数是**两个整数的比**，a/b 且 b ≠ 0。有三种理解要掌握：部分—整体（4 等份中的 3 份）、除法（3 ÷ 4 = 0.75）、以及数线上的一个点。能在这三种理解之间自由转换，以后学有理数代数就会很轻松。快问快答：7/8 和 8/9 哪个更接近 1？',
      },
    },
  },
  {
    user: { en: 'Is it OK to use AI for my art homework?', hk: '我可唔可以用 AI 做視藝功課？', cn: '我可以用 AI 做美术作业吗？' },
    stages: [
      { stage: 'thinking', note: { en: 'Reading your question…', hk: '睇緊你條問題…', cn: '正在读你的问题…' } },
      { stage: 'guard', note: { en: 'Checking the responsible-use rules…', hk: '睇緊負責任使用守則…', cn: '正在检查负责任使用守则…' } },
      { stage: 'retrieval', note: { en: 'Opening the Dreamer ethics library…', hk: '打開 Dreamer 倫理庫…', cn: '正在打开 Dreamer 伦理库…' } },
      { stage: 'writing', note: { en: 'Writing an answer just for you…', hk: '寫緊一個專屬答案俾你…', cn: '正在为你写专属答案…' } },
    ],
    mode: 'HYBRID',
    kid_label: 'Thoughtful Creator',
    citations: [
      { kb: 'dreamer-ethical-ai', topic_id: 'ethical-ai-ip-01', title: 'AI and Your Creations' },
      { kb: 'dreamer-ethical-ai', topic_id: 'ethical-ai-responsible-use-01', title: 'When NOT to Use AI' },
    ],
    payload: {
      'P1-P3': {
        en: "Great question to ask before you start! Here's the deal: AI can help you **get ideas**, but the picture should be **yours**. It's like a recipe book — looking is fine, but you still do the cooking. And always tell your teacher you used it, like saying 'thank you' to a helper. Want to make a little Creator's Promise card together?",
        hk: '開始之前識得問呢條問題，好好！咁樣諗啦：AI 可以幫你**諗橋**，但幅畫要係**你自己畫**。就好似食譜咁——睇人哋嘅食譜冇問題，但煮餸嗰個係你。仲有，記得話俾老師知你用過 AI，就好似同幫手講「唔該」一樣。想唔想同我一齊整張「創作者承諾卡」？',
        cn: '开始前先问这个问题，很棒！这样想：AI 可以帮你**出主意**，但画要是**你自己画的**。就像看菜谱——看别人的没问题，但做菜的是你。还有，记得告诉老师你用过 AI，就像跟帮手说「谢谢」一样。要不要跟我一起做一张「创作者承诺卡」？',
      },
      'P4-P6': {
        en: "Asking first = already doing it right. Short answer: **yes, with two rules**. Rule 1 — use AI for ideas and drafts, not the final piece you hand in. Rule 2 — add a credits note: which tool, what it made, what you changed. That's the **Creator's Pledge**: five lines that keep you honest and proud of your work. Shall we draft yours now?",
        hk: '識得先問已經係做啱咗第一步。簡單答你：**可以，但有兩條規矩**。第一——AI 用嚟諗橋同起稿，唔係交出去嗰份成品。第二——加一個鳴謝欄：用咗邊個工具、佢做咗啲咩、你改咗啲咩。呢個就係**創作者承諾**：五行字，令你做得誠實又自豪。不如而家一齊草擬你嗰份？',
        cn: '懂得先问，已经做对了第一步。简单回答：**可以，但有两条规则**。第一——AI 用来出主意和起草，不是你交上去的成品。第二——加一个致谢栏：用了哪个工具、它做了什么、你改了什么。这就是**创作者承诺**：五行字，让你做得诚实又自豪。不如现在一起起草你那份？',
      },
      'S1-S3': {
        en: "The honest answer is: it depends on what the homework is assessing. If the teacher is grading **your** composition and technique, a fully AI-generated image misrepresents your ability — that's the same category as copying. If it's graded on concept and iteration, AI sketches are a legitimate tool **as long as you disclose them**. The professional norm is a credits block: tool, prompt intent, what you kept, what you changed. Want to look at the exam-hall edge case — where the answer is simply no?",
        hk: '老實答你：要睇份功課考緊你咩。如果老師評分嘅係**你嘅**構圖同技巧，交一幅全 AI 生成嘅圖就等於呃緊人——同抄襲係同一類。如果評分嘅係概念同迭代過程，AI 草圖係正當工具，**前提係你要申報**。業界標準做法係加一個鳴謝欄：工具、指令意圖、你保留咗咩、改咗咩。想唔想睇下一個極端情況——考試場景，答案就係硬淨一個「唔得」？',
        cn: '诚实的回答是：要看这份作业考的是什么。如果老师评的是**你的**构图和技巧，交一幅全 AI 生成的图就等于误导——和抄袭是同一类。如果评的是概念和迭代过程，AI 草图是正当工具，**前提是你如实申报**。业界的标准做法是加一个致谢栏：工具、指令意图、你保留了什么、改了什么。想不想看一个极端情况——考试场景，答案就是干脆的「不行」？',
      },
    },
  },
];
