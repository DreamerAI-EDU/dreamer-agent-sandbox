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
  // forgot-password (W4 PR-D)
  forgotTitle: string;
  forgotSubtitle: string;
  forgotBtn: string;
  forgotSent: string;
  resetTitle: string;
  resetSubtitle: string;
  newPassword: string;
  confirmPassword: string;
  resetBtn: string;
  resetDone: string;
  resetInvalid: string;
  backToLogin: string;
  // consent
  consentTitle: string;
  consentSubtitle: string;
  consentPrivacy: string;
  consentPrivacyDesc: string;
  consentMedia: string;
  consentMediaDesc: string;
  consentChat: string;
  consentChatDesc: string;
  // staff data-processing notice (W6 PR-G, teacher / admin scope)
  consentStaffData: string;
  consentStaffDataDesc: string;
  consentRequired: string;
  consentBtn: string;
  consentBtnDisabled: string;
  consentDone: string;
  readPolicy: string;
  // consent withdraw (W6 PR-E)
  consentPanelTitle: string;
  consentNotSigned: string;
  consentAgreed: string;
  consentWithdrawn: string;
  consentWithdrawBtn: string;
  consentWithdrawingBtn: string;
  consentDialogTitle: string;
  consentDialogCancel: string;
  consentDialogConfirm: string;
  consentChatEffect: string;
  consentMediaEffect: string;
  consentWithdrawSuccess: string;
  consentWithdrawFailed: string;
  // invite
  inviteTitle: string;
  inviteSubtitle: string;
  inviteLang: string;
  inviteName: string;
  inviteAge: string;
  inviteBandLabel: string;
  inviteEmail: string;
  invitePasswordHint: string;
  invitePrivacyMust: string;
  inviteConsentRequiredTag: string;
  inviteMedia: string;
  inviteConsentOptionalTag: string;
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
  // Bridge-3b — Parent Console 8-week course map
  weekMapTitle: string;
  weekMapSubtitle: string;
  weekMapNeutral: string;
  weekMapCurrentWeek: string;
  weekMapNoData: string;
  weekMapMastery: string;
  weekMapStatusLocked: string;
  weekMapStatusActive: string;
  weekMapStatusCompleted: string;
  weekMapLegend: string;
  // Bridge-3c — Teacher Console: open a class / mount the 8-week course
  newClassBtn: string;
  newClassTitle: string;
  classNameLabel: string;
  classNamePlaceholder: string;
  classTypeLabel: string;
  classTypeMonthly: string;
  classTypeWorkshop: string;
  gradeBandLabel: string;
  gradeBandNone: string;
  createClassBtn: string;
  createClassHint: string;
  cancelBtn: string;
  closeBtn: string;
  mountTitle: string;
  mountCourseLabel: string;
  mountCourseEmpty: string;
  mountBtn: string;
  mountLaterBtn: string;
  mountAlready: string;
  mountDoneNote: string;
  courseChipNone: string;
  courseProgressTitle: string;
  courseProgressWeekPrefix: string;
  courseProgressWeekSuffix: string;
  courseProgressClassMastery: string;
  courseProgressNextWeek: string;
  courseProgressCompleted: string;
  // Bridge-3c — Teacher Console: 進度 card + 邀請 entry (掣 3 & 4)
  courseProgressNoCourse: string;
  courseProgressAdvanced: string;
  courseProgressAdvancing: string;
  inviteStudentBtn: string;
  inviteStudentTitle: string;
  inviteStudentHint: string;
  inviteFirstNameLabel: string;
  inviteFirstNamePlaceholder: string;
  inviteLangLabel: string;
  invitePinLabel: string;
  invitePinPlaceholder: string;
  invitePinInvalid: string;
  inviteSendBtn: string;
  inviteSentTitle: string;
  inviteSentEmailNote: string;
  inviteSentPinNote: string;
  invitePendingNote: string;
  inviteCopyPinBtn: string;
  inviteCopied: string;
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
  forgotTitle: 'Reset your password',
  forgotSubtitle: 'Enter your account email and we will send you a reset link.',
  forgotBtn: 'Send reset link',
  forgotSent: 'If an account exists for this email, a reset link has been sent.',
  resetTitle: 'Set a new password',
  resetSubtitle: 'Choose a new password for your account.',
  newPassword: 'New password',
  confirmPassword: 'Confirm new password',
  resetBtn: 'Reset password',
  resetDone: 'Password updated. Please sign in with your new password.',
  resetInvalid: 'This link is invalid or has expired.',
  backToLogin: 'Back to sign in',
  consentTitle: 'Consent required',
  consentSubtitle: 'Please review and agree to the documents below to continue.',
  consentPrivacy: 'Privacy Policy',
  consentPrivacyDesc: 'Required — how we collect and use your data.',
  consentMedia: 'Media Consent',
  consentMediaDesc: 'Optional — allow the use of child media in class materials.',
  consentChat: 'AI Chat Service Consent',
  consentChatDesc: 'Required — how AI chat messages are handled.',
  consentStaffData: 'Staff Data Processing Notice',
  consentStaffDataDesc: 'Required for staff — how you may access and handle student data.',
  consentRequired: 'Required',
  consentBtn: 'Agree & continue',
  consentBtnDisabled: 'All required documents must be agreed',
  consentDone: 'Consent saved',
  readPolicy: 'Read the full text',
  consentPanelTitle: 'Consent & withdrawal',
  consentNotSigned: 'Not signed',
  consentAgreed: 'Agreed',
  consentWithdrawn: 'Withdrawn',
  consentWithdrawBtn: 'Withdraw',
  consentWithdrawingBtn: 'Withdrawing…',
  consentDialogTitle: 'Withdraw consent?',
  consentDialogCancel: 'Cancel',
  consentDialogConfirm: 'Withdraw',
  consentChatEffect: 'AI chat will stop immediately for this child. No new AI chat session can start until you agree again.',
  consentMediaEffect: 'Media already collected will be taken down within 24 hours.',
  consentWithdrawSuccess: 'Consent withdrawn.',
  consentWithdrawFailed: 'Withdrawal failed. Please try again.',
  inviteTitle: 'Welcome to Dreamer AI',
  inviteSubtitle: 'Set your password to activate your parent account.',
  inviteName: 'Child',
  inviteAge: 'Age band',
  inviteBandLabel: 'Age band',
  inviteLang: 'Language',
  inviteEmail: 'Parent email',
  invitePasswordHint: 'Password',
  invitePrivacyMust: 'I agree to the Privacy Policy and the AI Chat Service Consent',
  inviteConsentRequiredTag: '[Required]',
  inviteMedia: 'I agree to the Media Consent',
  inviteConsentOptionalTag: '[Optional]',
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
  weekMapTitle: '8-week course map',
  weekMapSubtitle: 'Where your child is in the course right now.',
  weekMapNeutral:
    'Your child is not in a course yet — this map appears once the teacher mounts the 8-week course.',
  weekMapCurrentWeek: 'This week',
  weekMapNoData: 'No data yet',
  weekMapMastery: 'Mastery',
  weekMapStatusLocked: 'Locked',
  weekMapStatusActive: 'In progress',
  weekMapStatusCompleted: 'Completed',
  weekMapLegend: 'Locked · In progress · Completed',
  // Bridge-3c — Teacher Console: open a class / mount the 8-week course
  newClassBtn: 'New class',
  newClassTitle: 'New class',
  classNameLabel: 'Class name',
  classNamePlaceholder: 'e.g. P3 Phonics — Sat 10am',
  classTypeLabel: 'Class type',
  classTypeMonthly: 'Monthly',
  classTypeWorkshop: 'Workshop',
  gradeBandLabel: 'Grade band',
  gradeBandNone: 'Not set',
  createClassBtn: 'Create class',
  createClassHint: 'Next: mount the 8-week course for this class.',
  cancelBtn: 'Cancel',
  closeBtn: 'Done',
  mountTitle: 'Mount 8-week course',
  mountCourseLabel: 'Course',
  mountCourseEmpty: 'No ready 8-week course is available yet.',
  mountBtn: 'Mount course',
  mountLaterBtn: 'Not now',
  mountAlready: 'This class already has a course.',
  mountDoneNote: 'Week 1 is open — weeks 2–8 unlock one at a time.',
  courseChipNone: 'No course',
  courseProgressTitle: 'Weekly progress',
  courseProgressWeekPrefix: 'Week ',
  courseProgressWeekSuffix: ' / 8',
  courseProgressClassMastery: 'Class average mastery',
  courseProgressNextWeek: 'Advance to next week',
  courseProgressCompleted: 'All 8 weeks completed',
  // Bridge-3c — Teacher Console: 進度 card + 邀請 entry (掣 3 & 4)
  courseProgressNoCourse: 'No 8-week course is mounted for this class yet.',
  courseProgressAdvanced: 'Week closed — the next week is now open.',
  courseProgressAdvancing: 'Advancing…',
  inviteStudentBtn: 'Invite parent',
  inviteStudentTitle: 'Invite a parent',
  inviteStudentHint:
    'Creates the student, a pending class membership and a 72-hour invite email.',
  inviteFirstNameLabel: "Child's first name",
  inviteFirstNamePlaceholder: 'e.g. Eason',
  inviteLangLabel: "Child's language",
  invitePinLabel: 'Login PIN (optional)',
  invitePinPlaceholder: 'Blank = auto-generate',
  invitePinInvalid: 'PIN must be exactly 4 digits.',
  inviteSendBtn: 'Send invite',
  inviteSentTitle: 'Invite sent',
  inviteSentEmailNote: 'The confirmation link has been emailed to the parent (valid 72 hours).',
  inviteSentPinNote: "Child's login PIN — hand this to the parent:",
  invitePendingNote: 'The student stays pending until the parent confirms.',
  inviteCopyPinBtn: 'Copy PIN',
  inviteCopied: 'Copied',
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
  forgotTitle: '重設密碼',
  forgotSubtitle: '輸入帳號 email，我哋會寄重設連結俾你。',
  forgotBtn: '寄出重設連結',
  forgotSent: '如帳號存在，重設連結已寄出。',
  resetTitle: '設定新密碼',
  resetSubtitle: '為帳號設定新密碼。',
  newPassword: '新密碼',
  confirmPassword: '確認新密碼',
  resetBtn: '重設密碼',
  resetDone: '密碼已更新，請用新密碼登入。',
  resetInvalid: '此連結無效或已過期。',
  backToLogin: '返回登入',
  consentTitle: '需要簽署同意書',
  consentSubtitle: '請查閱並同意以下文件後繼續。',
  consentPrivacy: '私隱政策',
  consentPrivacyDesc: '必須 — 我哋點樣收集同使用你嘅資料。',
  consentMedia: '媒體同意書',
  consentMediaDesc: '可選 — 容許課堂教材使用小朋友嘅媒體。',
  consentChat: 'AI 對話服務同意書',
  consentChatDesc: '必需 — AI 對話內容嘅處理方式。',
  consentStaffData: '職員資料處理守則',
  consentStaffDataDesc: '職員必簽 — 查閱及處理學生資料之規範。',
  consentRequired: '必須',
  consentBtn: '同意並繼續',
  consentBtnDisabled: '必須同意所有必須文件',
  consentDone: '已記錄同意',
  readPolicy: '閱讀全文',
  consentPanelTitle: '同意及撤回管理',
  consentNotSigned: '未簽署',
  consentAgreed: '已同意',
  consentWithdrawn: '已撤回',
  consentWithdrawBtn: '撤回同意',
  consentWithdrawingBtn: '撤回中…',
  consentDialogTitle: '確認撤回同意？',
  consentDialogCancel: '取消',
  consentDialogConfirm: '確認撤回',
  consentChatEffect: '撤回後，呢位小朋友嘅 AI 對話會即時停止；要重新同意先可以再開始新對話。',
  consentMediaEffect: '已收集嘅媒體會喺 24 小時內下架。',
  consentWithdrawSuccess: '已撤回同意。',
  consentWithdrawFailed: '撤回失敗，請再試一次。',
  inviteTitle: '歡迎加入 Dreamer AI',
  inviteSubtitle: '設定密碼即可啟用家長帳號。',
  inviteName: '小朋友',
  inviteAge: '年齡組別',
  inviteBandLabel: '年齡組別',
  inviteLang: '語言',
  inviteEmail: '家長電郵',
  invitePasswordHint: '密碼',
  invitePrivacyMust: '我同意《私隱政策》及《AI 對話服務同意書》',
  inviteConsentRequiredTag: '【必需】',
  inviteMedia: '我同意《媒體同意書》',
  inviteConsentOptionalTag: '【自願】',
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
  weekMapTitle: '8 週課程地圖',
  weekMapSubtitle: '小朋友而家喺課程入面嘅位置。',
  weekMapNeutral: '小朋友暫時未入課程——老師掛上 8 週課程之後，呢幅地圖就會出現。',
  weekMapCurrentWeek: '今週',
  weekMapNoData: '未有數據',
  weekMapMastery: '掌握度',
  weekMapStatusLocked: '未開啟',
  weekMapStatusActive: '進行中',
  weekMapStatusCompleted: '已完成',
  weekMapLegend: '未開啟 · 進行中 · 已完成',
  // Bridge-3c — 老師工作台：開班 / 掛載 8 週課程
  newClassBtn: '開新班',
  newClassTitle: '開新班',
  classNameLabel: '班名',
  classNamePlaceholder: '例：P3 拼音班 — 星期六 10am',
  classTypeLabel: '班別類型',
  classTypeMonthly: '月費持續班',
  classTypeWorkshop: '工作坊',
  gradeBandLabel: '年級組',
  gradeBandNone: '不指定',
  createClassBtn: '開班',
  createClassHint: '下一步：為呢班掛上 8 週課程。',
  cancelBtn: '取消',
  closeBtn: '完成',
  mountTitle: '掛載 8 週課程',
  mountCourseLabel: '課程',
  mountCourseEmpty: '暫時未有可以掛載嘅 8 週課程。',
  mountBtn: '掛載課程',
  mountLaterBtn: '遲啲先',
  mountAlready: '呢班已經有課程。',
  mountDoneNote: '第 1 週已開啟——第 2 至 8 週會逐週解鎖。',
  courseChipNone: '未掛課程',
  courseProgressTitle: '每週進度',
  courseProgressWeekPrefix: '第 ',
  courseProgressWeekSuffix: ' 週 / 共 8 週',
  courseProgressClassMastery: '全班平均掌握度',
  courseProgressNextWeek: '推進下一週',
  courseProgressCompleted: '8 週已完成',
  // Bridge-3c — 老師工作台：進度卡 + 邀請入口（掣 3、4）
  courseProgressNoCourse: '呢班暫時未掛 8 週課程。',
  courseProgressAdvanced: '已完結本週——下一週已開啟。',
  courseProgressAdvancing: '推進中…',
  inviteStudentBtn: '邀請家長',
  inviteStudentTitle: '邀請家長加入',
  inviteStudentHint: '會建立學生、待確認班籍，並發出 72 小時有效嘅邀請電郵。',
  inviteFirstNameLabel: '小朋友名字',
  inviteFirstNamePlaceholder: '例：家豪',
  inviteLangLabel: '小朋友語言',
  invitePinLabel: '登入 PIN（可留空）',
  invitePinPlaceholder: '留空＝由系統產生',
  invitePinInvalid: 'PIN 必須係 4 位數字。',
  inviteSendBtn: '發送邀請',
  inviteSentTitle: '已發出邀請',
  inviteSentEmailNote: '確認連結已電郵俾家長（72 小時內有效）。',
  inviteSentPinNote: '小朋友登入 PIN——請轉交家長：',
  invitePendingNote: '家長確認之前，學生會維持「待確認」狀態。',
  inviteCopyPinBtn: '複製 PIN',
  inviteCopied: '已複製',
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
  forgotTitle: '重置密码',
  forgotSubtitle: '输入账号邮箱，我们会发送重置链接给你。',
  forgotBtn: '发送重置链接',
  forgotSent: '如账号存在，重置链接已发送。',
  resetTitle: '设置新密码',
  resetSubtitle: '为账号设置新密码。',
  newPassword: '新密码',
  confirmPassword: '确认新密码',
  resetBtn: '重置密码',
  resetDone: '密码已更新，请用新密码登录。',
  resetInvalid: '此链接无效或已过期。',
  backToLogin: '返回登录',
  consentTitle: '需要签署同意书',
  consentSubtitle: '请查阅并同意以下文件后继续。',
  consentPrivacy: '隐私政策',
  consentPrivacyDesc: '必须 — 我们如何收集和使用你的数据。',
  consentMedia: '媒体同意书',
  consentMediaDesc: '可选 — 允许课堂教材使用孩子的媒体。',
  consentChat: 'AI 对话服务同意书',
  consentChatDesc: '必需 — AI 对话内容的处理方式。',
  consentStaffData: '职员数据处理守则',
  consentStaffDataDesc: '职员必签 — 你查阅和处理学生资料的规范。',
  consentRequired: '必须',
  consentBtn: '同意并继续',
  consentBtnDisabled: '必须同意所有必须文件',
  consentDone: '已记录同意',
  readPolicy: '阅读全文',
  consentPanelTitle: '同意及撤回管理',
  consentNotSigned: '未签署',
  consentAgreed: '已同意',
  consentWithdrawn: '已撤回',
  consentWithdrawBtn: '撤回同意',
  consentWithdrawingBtn: '撤回中…',
  consentDialogTitle: '确认撤回同意？',
  consentDialogCancel: '取消',
  consentDialogConfirm: '确认撤回',
  consentChatEffect: '撤回后，这位孩子的 AI 对话会立即停止；需要重新同意才能再次开始新对话。',
  consentMediaEffect: '已收集的媒体会在 24 小时内下架。',
  consentWithdrawSuccess: '已撤回同意。',
  consentWithdrawFailed: '撤回失败，请再试一次。',
  inviteTitle: '欢迎加入 Dreamer AI',
  inviteSubtitle: '设置密码即可启用家长账号。',
  inviteName: '孩子',
  inviteAge: '年龄组别',
  inviteBandLabel: '年龄组别',
  inviteLang: '语言',
  inviteEmail: '家长邮箱',
  invitePasswordHint: '密码',
  invitePrivacyMust: '我同意《隐私政策》及《AI 对话服务同意书》',
  inviteConsentRequiredTag: '【必需】',
  inviteMedia: '我同意《媒体同意书》',
  inviteConsentOptionalTag: '【自願】',
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
  weekMapTitle: '8 周课程地图',
  weekMapSubtitle: '孩子现在在课程里的位置。',
  weekMapNeutral: '孩子暂时还没有进入课程——老师挂上 8 周课程后，这张地图就会出现。',
  weekMapCurrentWeek: '本周',
  weekMapNoData: '暂无数据',
  weekMapMastery: '掌握度',
  weekMapStatusLocked: '未开启',
  weekMapStatusActive: '进行中',
  weekMapStatusCompleted: '已完成',
  weekMapLegend: '未开启 · 进行中 · 已完成',
  // Bridge-3c — 老师工作台：开新班 / 挂载 8 周课程
  newClassBtn: '新建班级',
  newClassTitle: '新建班级',
  classNameLabel: '班级名称',
  classNamePlaceholder: '例：P3 拼音班 — 周六 10点',
  classTypeLabel: '班级类型',
  classTypeMonthly: '月费班',
  classTypeWorkshop: '工作坊',
  gradeBandLabel: '年级组',
  gradeBandNone: '不设置',
  createClassBtn: '创建班级',
  createClassHint: '下一步：为这个班挂载 8 周课程。',
  cancelBtn: '取消',
  closeBtn: '完成',
  mountTitle: '挂载 8 周课程',
  mountCourseLabel: '课程',
  mountCourseEmpty: '暂时没有可挂载的 8 周课程。',
  mountBtn: '挂载课程',
  mountLaterBtn: '以后再说',
  mountAlready: '这个班已经有课程。',
  mountDoneNote: '第 1 周已开启——第 2 至 8 周会逐周解锁。',
  courseChipNone: '未挂课程',
  courseProgressTitle: '每周进度',
  courseProgressWeekPrefix: '第 ',
  courseProgressWeekSuffix: ' 周 / 共 8 周',
  courseProgressClassMastery: '全班平均掌握度',
  courseProgressNextWeek: '推进下一周',
  courseProgressCompleted: '8 周已完成',
  // Bridge-3c — 老师工作台：进度卡 + 邀请入口（按钮 3、4）
  courseProgressNoCourse: '这个班暂时还没挂载 8 周课程。',
  courseProgressAdvanced: '本周已结束——下一周已开启。',
  courseProgressAdvancing: '推进中…',
  inviteStudentBtn: '邀请家长',
  inviteStudentTitle: '邀请家长加入',
  inviteStudentHint: '会创建学生、待确认班籍，并发出 72 小时有效的邀请邮件。',
  inviteFirstNameLabel: '孩子名字',
  inviteFirstNamePlaceholder: '例：家豪',
  inviteLangLabel: '孩子语言',
  invitePinLabel: '登录 PIN（可留空）',
  invitePinPlaceholder: '留空＝由系统生成',
  invitePinInvalid: 'PIN 必须是 4 位数字。',
  inviteSendBtn: '发送邀请',
  inviteSentTitle: '邀请已发出',
  inviteSentEmailNote: '确认链接已发送到家长邮箱（72 小时内有效）。',
  inviteSentPinNote: '孩子登录 PIN——请转交家长：',
  invitePendingNote: '家长确认之前，学生会保持“待确认”状态。',
  inviteCopyPinBtn: '复制 PIN',
  inviteCopied: '已复制',
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
