// Kid-safe error + connection copy (en / hk / cn).
// Raw error strings NEVER reach the UI — this module is the only source of
// child-facing wording for the WS chat connection states.

export type KidErrorKind =
  | 'no-student' // profile present but no student mask in the URL (deep link)
  | 'auth' // WS handshake rejected: session missing / expired (401 class)
  | 'permission' // WS handshake rejected: ownership / not confirmed (403 class)
  | 'network' // transport-level failure (cannot reach server)
  | 'upstream' // server relay / DeepTutor turn rejected with an error frame
  | 'turn-lost'; // reconnect succeeded but the server no longer replays the turn

export type ChatStreamStatus =
  | 'idle' // no connection in flight (before ask / after terminal done)
  | 'connecting' // first socket opening
  | 'streaming' // connected, events flowing
  | 'disconnected' // socket dropped, backoff running
  | 'reconnecting' // retry in progress
  | 'failed'; // turn ended with a kid-safe error

export interface KidErrorCopy {
  title: Record<LangId, string>;
  hint: Record<LangId, string>; // extra line, may be empty
}

type LangId = 'en' | 'hk' | 'cn';

export const STATUS_COPY: Record<'connecting' | 'disconnected' | 'reconnecting', Record<LangId, string>> = {
  connecting: { en: 'Connecting to Dibi…', hk: '連緊 Dibi…', cn: '正在连接 Dibi…' },
  disconnected: { en: 'Connection lost…', hk: '連線斷咗…', cn: '连接断了…' },
  reconnecting: { en: 'Dibi is trying to reconnect…', hk: 'Dibi 試緊連返…', cn: 'Dibi 正在重新连接…' },
};

export const ERROR_COPY: Record<KidErrorKind, KidErrorCopy> = {
  'no-student': {
    title: {
      en: 'Pick a child and enter the PIN to start chatting.',
      hk: '揀小朋友並輸入 PIN 先可以開始對話。',
      cn: '选择孩子并输入 PIN 才能开始对话。',
    },
    hint: { en: '', hk: '', cn: '' },
  },
  auth: {
    title: {
      en: 'This chat needs a grown-up to sign in again.',
      hk: '呢個聊天要大人重新登入先開到。',
      cn: '这个聊天需要大人重新登录才能打开。',
    },
    hint: {
      en: 'Ask your grown-up to come back and sign in.',
      hk: '叫大人返嚟重新登入就可以啦。',
      cn: '请大人回来重新登录就可以了。',
    },
  },
  permission: {
    title: {
      en: 'Chatting is not switched on for this child yet.',
      hk: '呢位小朋友仲未開通聊天。',
      cn: '这个小朋友还没开通聊天。',
    },
    hint: {
      en: 'Ask a grown-up to check the class confirmation.',
      hk: '問吓大人，睇下課堂確認咗未。',
      cn: '问问大人，看看课堂确认了没有。',
    },
  },
  network: {
    title: {
      en: 'The connection dropped for a moment.',
      hk: '網絡斷咗線。',
      cn: '网络断了一下。',
    },
    hint: {
      en: 'Check the Wi-Fi, then tap Try again.',
      hk: '睇下 Wi-Fi，再撳「再試一次」。',
      cn: '看看 Wi-Fi，再点「再试一次」。',
    },
  },
  upstream: {
    title: {
      en: 'Dibi hit a little hiccup.',
      hk: 'Dibi 撞到少少問題。',
      cn: 'Dibi 遇到点小问题。',
    },
    hint: {
      en: 'Ask again in a little while.',
      hk: '等陣再問過啦。',
      cn: '等一会儿再问一次吧。',
    },
  },
  'turn-lost': {
    title: {
      en: 'That answer got cut off.',
      hk: '頭先個答案斷咗線。',
      cn: '刚才的答案断线了。',
    },
    hint: {
      en: 'Tap Ask again — Dibi will start fresh.',
      hk: '再撳「問 Dibi」，佢會重新答你。',
      cn: '再点「问 Dibi」，它会重新回答你。',
    },
  },
};

export const RETRY_LABEL: Record<LangId, string> = {
  en: 'Try again',
  hk: '再試一次',
  cn: '再试一次',
};
