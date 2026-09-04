// W2 PR#6 — minimal UI language context for the five real pages.
// Persists the preference in localStorage (never any student id / PIN).
// Keys: en / hk (廣東話) / cn (简体).

import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

export type UiLang = 'en' | 'hk' | 'cn';

export const UI_LANGS: { code: UiLang; label: string }[] = [
  { code: 'en', label: 'EN' },
  { code: 'hk', label: '粵' },
  { code: 'cn', label: '简' },
];

const STORAGE_KEY = 'dreamer.ui.lang';

export interface Copy {
  brand: string;
  backToHome: string;
  signOut: string;
  // login
  loginTitle: string;
  loginSubtitle: string;
  email: string;
  password: string;
  loginBtn: string;
  loginError: string;
  loginNote: string;
  // consent
  consentTitle: string;
  consentSubtitle: string;
  consentPrivacy: string;
  consentPrivacyDesc: string;
  consentMedia: string;
  consentMediaDesc: string;
  consentRequired: string;
  consentBtn: string;
  consentBtnDisabled: string;
  consentDone: string;
  readPolicy: string;
  // invite
  inviteTitle: string;
  inviteSubtitle: string;
  inviteName: string;
  inviteAge: string;
  inviteBandLabel: string;
  inviteEmail: string;
  invitePasswordHint: string;
  invitePrivacyMust: string;
  inviteMedia: string;
  inviteBtn: string;
  inviteInvalidTitle: string;
  inviteInvalidDesc: string;
  contactEmail: string;
  passwordPolicy: string;
  // home / PIN
  homeTitle: string;
  homeSubtitle: string;
  selectStudent: string;
  pinTitle: string;
  pinSubtitle: string;
  pinPlaceholder: string;
  pinVerifyBtn: string;
  pinResetBtn: string;
  pinResetTitle: string;
  pinResetSelf: string;
  pinResetGenerate: string;
  pinResetGenerateDesc: string;
  pinResetSubmit: string;
  pinNewPin: string;
  pinSaveNotice: string;
  pinCancel: string;
  noStudents: string;
  goChat: string;
  // safety
  safetyTitle: string;
  safetySubtitle: string;
  safetyUnreviewedOnly: string;
  safetyEmpty: string;
  safetyStudent: string;
  safetyType: string;
  safetySeverity: string;
  safetyTime: string;
  safetyStatus: string;
  safetyReviewed: string;
  safetyUnreviewed: string;
  safetyView: string;
  safetyDetail: string;
  safetyRaw: string;
  safetyMarkReviewed: string;
  safetyStepUpTitle: string;
  safetyStepUpDesc: string;
  safetyStepUpBtn: string;
  safetyStepUpWrong: string;
  safetyClose: string;
  // teacher console (W3-C)
  teacherConsole: string;
  myClasses: string;
  emptyClasses: string;
  joinCodeLabel: string;
  pendingLabel: string;
  confirmedLabel: string;
  pendingStudentsTitle: string;
  noPendingStudents: string;
  ageBandLabel: string;
  classGroupMonthly: string;
  classGroupWorkshop: string;
  classGroupOther: string;
  oneOnOneBadge: string;
  // teacher register (W3-C)
  teacherRegisterTitle: string;
  teacherRegisterSubtitle: string;
  inviteCodeLabel: string;
  registerBtn: string;
  registerNote: string;
  teacherSideNote: string;
  // teacher register — verify step
  alreadyHaveAccount: string;
  verifyTitle: string;
  verifySubtitle: string;
  verifyCodeLabel: string;
  verifyBtn: string;
  verifyDoneTitle: string;
  verifyDoneDesc: string;
  goLogin: string;
  // errors / generic
  loading: string;
  retry: string;
  unexpectedError: string;
  ageBands: Record<string, string>;
}

export const copyEn: Copy = {
  brand: 'Dreamer AI',
  backToHome: 'Back',
  signOut: 'Sign out',
  loginTitle: 'Sign in to Dreamer AI',
  loginSubtitle: 'Parent, teacher and admin accounts sign in here.',
  email: 'Email',
  password: 'Password',
  loginBtn: 'Sign in',
  loginError: 'Unable to sign in',
  loginNote: 'Wrong password too many times will lock the account temporarily.',
  consentTitle: 'Consent required',
  consentSubtitle: 'Please review and agree to the documents below to continue.',
  consentPrivacy: 'Privacy Policy',
  consentPrivacyDesc: 'Required — how we collect and use your data.',
  consentMedia: 'Media Consent',
  consentMediaDesc: 'Optional — allow the use of child media in class materials.',
  consentRequired: 'Required',
  consentBtn: 'Agree & continue',
  consentBtnDisabled: 'Privacy Policy must be agreed',
  consentDone: 'Consent saved',
  readPolicy: 'Read the full text',
  inviteTitle: 'Welcome to Dreamer AI',
  inviteSubtitle: 'Set your password to activate your parent account.',
  inviteName: 'Child',
  inviteAge: 'Age band',
  inviteBandLabel: 'Age band',
  inviteEmail: 'Parent email',
  invitePasswordHint: 'Password',
  invitePrivacyMust: 'I agree to the Privacy Policy',
  inviteMedia: 'I agree to the Media Consent (optional)',
  inviteBtn: 'Activate account',
  inviteInvalidTitle: 'This invitation link is invalid or has expired',
  inviteInvalidDesc: 'Please ask the teacher to send a new invitation link.',
  contactEmail: 'Contact',
  passwordPolicy: 'At least 10 characters with letters and numbers',
  homeTitle: 'Choose a child',
  homeSubtitle: 'Select a child and enter the PIN to start.',
  selectStudent: 'Your children',
  pinTitle: 'Enter PIN',
  pinSubtitle: 'Enter the 4-digit PIN for this child.',
  pinPlaceholder: '4-digit PIN',
  pinVerifyBtn: 'Unlock',
  pinResetBtn: 'Forgot PIN?',
  pinResetTitle: 'Reset PIN',
  pinResetSelf: 'I will set a new 4-digit PIN',
  pinResetGenerate: 'Generate a PIN for me',
  pinResetGenerateDesc: 'A new PIN will be shown once — write it down.',
  pinResetSubmit: 'Reset PIN',
  pinNewPin: 'New PIN',
  pinSaveNotice: 'Save this PIN somewhere safe. It is shown only once.',
  pinCancel: 'Cancel',
  noStudents: 'No children have been added to your account yet.',
  goChat: 'Start chatting',
  safetyTitle: 'Safety review',
  safetySubtitle: 'Review flagged conversations for your classes.',
  safetyUnreviewedOnly: 'Unreviewed only',
  safetyEmpty: 'No safety events.',
  safetyStudent: 'Student',
  safetyType: 'Type',
  safetySeverity: 'Severity',
  safetyTime: 'Time',
  safetyStatus: 'Status',
  safetyReviewed: 'Reviewed',
  safetyUnreviewed: 'New',
  safetyView: 'View',
  safetyDetail: 'Safety event',
  safetyRaw: 'Original message',
  safetyMarkReviewed: 'Mark as reviewed',
  safetyStepUpTitle: 'Re-verify your password',
  safetyStepUpDesc: 'For your safety, re-enter your login password to view the full message.',
  safetyStepUpBtn: 'Verify',
  safetyStepUpWrong: 'Incorrect password.',
  safetyClose: 'Close',
  teacherConsole: 'Teacher Console',
  myClasses: 'My Classes',
  emptyClasses: 'No classes yet. Ask an admin to create one for you.',
  joinCodeLabel: 'Join code',
  pendingLabel: 'Pending',
  confirmedLabel: 'Confirmed',
  pendingStudentsTitle: 'Awaiting confirmation',
  noPendingStudents: 'No pending students.',
  ageBandLabel: 'Ages',
  classGroupMonthly: 'Monthly classes',
  classGroupWorkshop: 'Short workshops',
  classGroupOther: 'Other',
  oneOnOneBadge: '1-on-1',
  teacherRegisterTitle: 'Join Dreamer AI as a teacher',
  teacherRegisterSubtitle: 'Use the invite code from your school to create your teacher account.',
  inviteCodeLabel: 'Invite code',
  registerBtn: 'Create account',
  registerNote: 'After signing up we email you a verification code — enter it on the next step, then sign in.',
  teacherSideNote: 'Class schedules and bookings live in your external tools.',
  alreadyHaveAccount: 'Already have an account?',
  verifyTitle: 'Verify your email',
  verifySubtitle: 'We sent a verification code to',
  verifyCodeLabel: 'Verification code',
  verifyBtn: 'Verify',
  verifyDoneTitle: 'Email verified',
  verifyDoneDesc: 'Your teacher account is ready. Sign in to open your Teacher Console.',
  goLogin: 'Sign in now',
  loading: 'Loading…',
  retry: 'Retry',
  unexpectedError: 'Something went wrong.',
  ageBands: {
    'P1-P3': 'P1–P3',
    'P4-P6': 'P4–P6',
    'S1-S3': 'S1–S3',
  },
};

const copyHk: Copy = {
  brand: 'Dreamer AI',
  backToHome: '返回',
  signOut: '登出',
  loginTitle: '登入 Dreamer AI',
  loginSubtitle: '家長、老師同管理員帳號喺度登入。',
  email: '電郵',
  password: '密碼',
  loginBtn: '登入',
  loginError: '無法登入',
  loginNote: '密碼錯太多次會暫時鎖定帳號。',
  consentTitle: '需要簽署同意書',
  consentSubtitle: '請查閱並同意以下文件後繼續。',
  consentPrivacy: '私隱政策',
  consentPrivacyDesc: '必須 — 我哋點樣收集同使用你嘅資料。',
  consentMedia: '媒體同意書',
  consentMediaDesc: '可選 — 容許課堂教材使用小朋友嘅媒體。',
  consentRequired: '必須',
  consentBtn: '同意並繼續',
  consentBtnDisabled: '必須同意私隱政策',
  consentDone: '已記錄同意',
  readPolicy: '閱讀全文',
  inviteTitle: '歡迎加入 Dreamer AI',
  inviteSubtitle: '設定密碼即可啟用家長帳號。',
  inviteName: '小朋友',
  inviteAge: '年齡組別',
  inviteBandLabel: '年齡組別',
  inviteEmail: '家長電郵',
  invitePasswordHint: '密碼',
  invitePrivacyMust: '我同意私隱政策',
  inviteMedia: '我同意媒體同意書（可選）',
  inviteBtn: '啟用帳號',
  inviteInvalidTitle: '呢條邀請連結無效或已過期',
  inviteInvalidDesc: '請搵老師重新發送邀請連結。',
  contactEmail: '聯絡',
  passwordPolicy: '至少 10 位，包含字母同數字',
  homeTitle: '揀一位小朋友',
  homeSubtitle: '揀小朋友並輸入 PIN 開始。',
  selectStudent: '你嘅小朋友',
  pinTitle: '輸入 PIN',
  pinSubtitle: '輸入呢位小朋友嘅 4 位 PIN。',
  pinPlaceholder: '4 位 PIN',
  pinVerifyBtn: '解鎖',
  pinResetBtn: '唔記得 PIN？',
  pinResetTitle: '重設 PIN',
  pinResetSelf: '我自己設定新 4 位 PIN',
  pinResetGenerate: '幫我生成 PIN',
  pinResetGenerateDesc: '新 PIN 只會顯示一次 — 請抄低。',
  pinResetSubmit: '重設 PIN',
  pinNewPin: '新 PIN',
  pinSaveNotice: '請妥善保存呢個 PIN，只會顯示一次。',
  pinCancel: '取消',
  noStudents: '帳號暫時未加入任何小朋友。',
  goChat: '開始對話',
  safetyTitle: '安全審查',
  safetySubtitle: '檢查你班學生嘅標記對話。',
  safetyUnreviewedOnly: '只睇未審',
  safetyEmpty: '暫時冇安全事件。',
  safetyStudent: '學生',
  safetyType: '類型',
  safetySeverity: '嚴重程度',
  safetyTime: '時間',
  safetyStatus: '狀態',
  safetyReviewed: '已審',
  safetyUnreviewed: '新',
  safetyView: '睇',
  safetyDetail: '安全事件',
  safetyRaw: '原始訊息',
  safetyMarkReviewed: '標記為已審',
  safetyStepUpTitle: '重新驗證密碼',
  safetyStepUpDesc: '為咗安全，睇完整訊息前請重新輸入登入密碼。',
  safetyStepUpBtn: '驗證',
  safetyStepUpWrong: '密碼不正確。',
  safetyClose: '關閉',
  teacherConsole: '老師工作台',
  myClasses: '我的班級',
  emptyClasses: '未有班級。請搵管理員幫你開班。',
  joinCodeLabel: '邀請碼',
  pendingLabel: '待確認',
  confirmedLabel: '已確認',
  pendingStudentsTitle: '等緊確認嘅學生',
  noPendingStudents: '冇待確認學生。',
  ageBandLabel: '年齡',
  classGroupMonthly: '月費持續班',
  classGroupWorkshop: '短期工作坊',
  classGroupOther: '其他',
  oneOnOneBadge: '1對1',
  teacherRegisterTitle: '以老師身份加入 Dreamer AI',
  teacherRegisterSubtitle: '用學校畀你嘅邀請碼建立老師帳號。',
  inviteCodeLabel: '邀請碼',
  registerBtn: '建立帳號',
  registerNote: '註冊後我哋會 email 驗證碼畀你——喺下一步輸入，然後登入。',
  teacherSideNote: '班上時間地點由你嘅外部工具管理。',
  alreadyHaveAccount: '已經有帳號？',
  verifyTitle: '驗證你的電郵',
  verifySubtitle: '我哋已將驗證碼寄到',
  verifyCodeLabel: '驗證碼',
  verifyBtn: '驗證',
  verifyDoneTitle: '電郵已驗證',
  verifyDoneDesc: '老師帳號已就緒。登入後會嚟到老師工作台。',
  goLogin: '即刻登入',
  loading: '載入中…',
  retry: '重試',
  unexpectedError: '發生錯誤。',
  ageBands: {
    'P1-P3': 'P1–P3',
    'P4-P6': 'P4–P6',
    'S1-S3': 'S1–S3',
  },
};

const copyCn: Copy = {
  brand: 'Dreamer AI',
  backToHome: '返回',
  signOut: '登出',
  loginTitle: '登录 Dreamer AI',
  loginSubtitle: '家长、老师和管理员账号在此登录。',
  email: '邮箱',
  password: '密码',
  loginBtn: '登录',
  loginError: '无法登录',
  loginNote: '密码错误次数过多会暂时锁定账号。',
  consentTitle: '需要签署同意书',
  consentSubtitle: '请查阅并同意以下文件后继续。',
  consentPrivacy: '隐私政策',
  consentPrivacyDesc: '必须 — 我们如何收集和使用你的数据。',
  consentMedia: '媒体同意书',
  consentMediaDesc: '可选 — 允许课堂教材使用孩子的媒体。',
  consentRequired: '必须',
  consentBtn: '同意并继续',
  consentBtnDisabled: '必须同意隐私政策',
  consentDone: '已记录同意',
  readPolicy: '阅读全文',
  inviteTitle: '欢迎加入 Dreamer AI',
  inviteSubtitle: '设置密码即可启用家长账号。',
  inviteName: '孩子',
  inviteAge: '年龄组别',
  inviteBandLabel: '年龄组别',
  inviteEmail: '家长邮箱',
  invitePasswordHint: '密码',
  invitePrivacyMust: '我同意隐私政策',
  inviteMedia: '我同意媒体同意书（可选）',
  inviteBtn: '启用账号',
  inviteInvalidTitle: '此邀请链接无效或已过期',
  inviteInvalidDesc: '请联系老师重新发送邀请链接。',
  contactEmail: '联系',
  passwordPolicy: '至少 10 位，包含字母和数字',
  homeTitle: '选择孩子',
  homeSubtitle: '选择孩子并输入 PIN 开始。',
  selectStudent: '你的孩子',
  pinTitle: '输入 PIN',
  pinSubtitle: '输入该孩子的 4 位 PIN。',
  pinPlaceholder: '4 位 PIN',
  pinVerifyBtn: '解锁',
  pinResetBtn: '忘记 PIN？',
  pinResetTitle: '重置 PIN',
  pinResetSelf: '我自己设置新的 4 位 PIN',
  pinResetGenerate: '帮我生成 PIN',
  pinResetGenerateDesc: '新 PIN 只显示一次 — 请记下来。',
  pinResetSubmit: '重置 PIN',
  pinNewPin: '新 PIN',
  pinSaveNotice: '请妥善保存此 PIN，只显示一次。',
  pinCancel: '取消',
  noStudents: '账号暂未添加任何孩子。',
  goChat: '开始对话',
  safetyTitle: '安全审查',
  safetySubtitle: '检查你班学生的标记对话。',
  safetyUnreviewedOnly: '只看未审',
  safetyEmpty: '暂无安全事件。',
  safetyStudent: '学生',
  safetyType: '类型',
  safetySeverity: '严重程度',
  safetyTime: '时间',
  safetyStatus: '状态',
  safetyReviewed: '已审',
  safetyUnreviewed: '新',
  safetyView: '查看',
  safetyDetail: '安全事件',
  safetyRaw: '原始消息',
  safetyMarkReviewed: '标记为已审',
  safetyStepUpTitle: '重新验证密码',
  safetyStepUpDesc: '为安全起见，查看完整消息前请重新输入登录密码。',
  safetyStepUpBtn: '验证',
  safetyStepUpWrong: '密码不正确。',
  safetyClose: '关闭',
  teacherConsole: '老师工作台',
  myClasses: '我的班级',
  emptyClasses: '还没有班级。请联系管理员创建。',
  joinCodeLabel: '邀请码',
  pendingLabel: '待确认',
  confirmedLabel: '已确认',
  pendingStudentsTitle: '等待确认的学生',
  noPendingStudents: '没有待确认学生。',
  ageBandLabel: '年龄',
  classGroupMonthly: '月费持续班',
  classGroupWorkshop: '短期工作坊',
  classGroupOther: '其他',
  oneOnOneBadge: '1对1',
  teacherRegisterTitle: '以老师身份加入 Dreamer AI',
  teacherRegisterSubtitle: '使用学校发给你的邀请码创建老师账号。',
  inviteCodeLabel: '邀请码',
  registerBtn: '创建账号',
  registerNote: '注册后我们会把验证码发到你的邮箱——在下一步输入，然后登录。',
  teacherSideNote: '上课时间地点由你的外部工具管理。',
  alreadyHaveAccount: '已有账号？',
  verifyTitle: '验证你的邮箱',
  verifySubtitle: '我们已将验证码发送到',
  verifyCodeLabel: '验证码',
  verifyBtn: '验证',
  verifyDoneTitle: '邮箱已验证',
  verifyDoneDesc: '老师账号已就绪。登录后进入老师工作台。',
  goLogin: '立即登录',
  loading: '加载中…',
  retry: '重试',
  unexpectedError: '发生错误。',
  ageBands: {
    'P1-P3': 'P1–P3',
    'P4-P6': 'P4–P6',
    'S1-S3': 'S1–S3',
  },
};

const COPIES: Record<UiLang, Copy> = { en: copyEn, hk: copyHk, cn: copyCn };

interface LanguageContextValue {
  lang: UiLang;
  setLang: (lang: UiLang) => void;
  copy: Copy;
}

const LanguageContext = createContext<LanguageContextValue | null>(null);

function readStoredLang(): UiLang {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw === 'en' || raw === 'hk' || raw === 'cn') return raw;
  } catch {
    // localStorage unavailable — fall back to English.
  }
  return 'en';
}

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<UiLang>(readStoredLang);
  const setLang = (next: UiLang) => {
    setLangState(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Ignore persistence failures.
    }
  };
  const value = useMemo<LanguageContextValue>(
    () => ({ lang, setLang, copy: COPIES[lang] }),
    [lang],
  );
  useEffect(() => {
    document.documentElement.lang = lang === 'en' ? 'en' : lang === 'hk' ? 'zh-HK' : 'zh-CN';
  }, [lang]);
  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useLang(): LanguageContextValue {
  const ctx = useContext(LanguageContext);
  if (!ctx) throw new Error('useLang must be used inside LanguageProvider');
  return ctx;
}
