# Dreamer AI — Consent 條款定稿（W6）

> 本文檔為 W6 法律文案定稿（doc-only PR-A），屬 **唯一 SoT**（single source of truth）。
> 版本號由 `config/consent_docs.yaml` 單源注入（頁面以 `{{VERSION}}` 佔位），本檔不硬編版本號。
> 語言：繁體中文（zh-HK，為準）／简体中文（zh-CN）／English（en）。
> **譯本有歧義時，以繁體中文版本為準。**
> 生效日期：以上線時 `consent_docs.yaml` 對應 `current_version` 為準。

---

## 總覽（Implementation Note）

W6 決策 D-W6-2：**media_consent 與 chat 授權解耦**。平台設兩份獨立同意書，家長分別同意、分別撤回：

| 文件 | doc_type（consent_log） | 性質 | 撤回影響 |
|---|---|---|---|
| 媒體同意書 | `media_consent` | 自願 | 撤回後 24 小時內下架學生創作作品；**不影響 AI 對話功能** |
| AI 對話服務同意書 | `chat_consent`（新增） | 核心教學功能所需 | 撤回後停止 AI 對話功能；**不影響媒體展示** |

> 對應後端變更（PR-B/PR-D 範圍，非本 PR）：`consent_log` 支援獨立 `chat_consent` flag；gate 逐 flag 判斷，`ws_chat` 不再以 `media_consent` 撤回狀態剎停對話。

W6 PR-G：平台另設**職員專用**文件 `staff_data_processing`（職員資料處理守則），對象為 teacher / admin 帳號；家長文件（privacy / media / chat）同職員文件互不重疊（registry `roles:` 範圍控制），老師登入唔會再被家長門禁擋住。守則全文見本文件第三部分。

| 文件 | doc_type（consent_log） | roles | required | 撤回 |
|---|---|---|---|---|
| 私隱政策 | `privacy_policy` | parent | 是 | API 拒絕（帳戶層事項，電郵 info@） |
| 媒體同意書 | `media_consent` | parent | 否 | 允許（24h 下架流程） |
| AI 對話服務同意書 | `chat_consent` | parent | 是 | 允許（停 AI 對話） |
| 職員資料處理守則 | `staff_data_processing`（W6 PR-G 新增） | teacher, admin | 是 | API 拒絕（職員帳號層事項，電郵 info@） |

---

# 一、媒體同意書（Media Consent Form）

## 1A. 繁體中文（zh-HK · 為準）

### 學生作品媒體同意書

**1. 本文件之目的**

Dreamer AI 希望於官方宣傳渠道展示學生作品——例如頭像（avatar）畫作、海報、影片、遊戲項目及作品集項目。本文件旨在向家長或合法監護人徵求許可。簽署與否，純屬自願。

**2. 我們可能使用之內容及渠道**

經閣下同意後，我們可能於以下渠道使用學生之**創作作品**：

- 官方網站（dreamer-aiedu.com）
- 官方 Instagram、Facebook、小紅書、微信及 Threads 專頁
- 印刷宣傳品（例如小冊子、單張）

**3. 我們如何保障閣下子女之身份——始終如一**

- 在本同意書下，我們僅以學生之**名字（first name）及頭像（avatar）**展示其作品
- 我們**絕不**刊登學生全名、學校名稱、相片、露臉影片或任何聯絡資料，**除非閣下就該次特定用途另行作出具體書面批准**；閣下可隨時撤回該批准，並受本文件第 5 條之 24 小時下架承諾保障
- 作品僅以創作成果形式展示，絕不附帶評估成績或內部標籤

**4. 先批後用**

除非並直至家長或合法監護人簽署本同意書，否則我們**絕不**於任何宣傳渠道使用學生作品。

**5. 閣下之選擇完全自由**

- 同意純屬**自願**。拒絕不影響報讀、課程內容或閣下子女所獲之任何服務
- 閣下可**隨時撤回同意**，電郵 info@dreamer-aiedu.com 即可
- 撤回後，我們將於 **24 小時內**將學生作品從所有渠道下架

**6. 與 AI 對話功能之關係（解耦聲明）**

本同意書僅涵蓋學生創作作品之媒體展示，**與平台之 AI 對話教學功能並無關連**。撤回本同意書**不會**影響 AI 對話功能之運作；同樣，撤回 AI 對話服務同意書亦不會影響本同意書之效力。

**7. 有效期**

本同意書有效期為學生課程期間**加 12 個月**。期滿後我們將停止使用相關作品；如需續期，我們將聯絡閣下重新簽署。

### 同意聲明

請於其中一個方格加上 ✓：

- ☐ 本人**同意** Dreamer AI 按上述方式使用本人子女之創作作品。
- ☐ 本人**不同意** Dreamer AI 使用本人子女之創作作品。

| 項目 | 填寫 |
|---|---|
| 學生名字（first name） | ____________________ |
| 家長／監護人姓名 | ____________________ |
| 與學生關係 | ____________________ |
| 簽署 | ____________________ |
| 日期 | ____________________ |

---

## 1B. 简体中文（zh-CN · 译文）

### 学生作品媒体同意书

**1. 本文件之目的**

Dreamer AI 希望在官方宣传渠道展示学生作品——例如头像（avatar）画作、海报、视频、游戏项目及作品集项目。本文件旨在征询家长或合法监护人的许可。是否签署，纯属自愿。

**2. 我们可能使用的内容及渠道**

经您同意后，我们可能在以下渠道使用学生的**创作作品**：

- 官方网站（dreamer-aiedu.com）
- 官方 Instagram、Facebook、小红书、微信及 Threads 专页
- 印刷宣传品（例如宣传册、单张）

**3. 我们如何保障您子女的身份——始终如一**

- 在本同意书下，我们仅以学生的**名字（first name）及头像（avatar）**展示其作品
- 我们**绝不**刊登学生全名、学校名称、照片、露脸视频或任何联系方式，**除非您就该次特定用途另行作出具体书面批准**；您可随时撤回该批准，并受本文件第 5 条之 24 小时下架承诺保障
- 作品仅以创作成果形式展示，绝不附带评估成绩或内部标签

**4. 先批准后使用**

除非并直至家长或合法监护人签署本同意书，否则我们**绝不**在任何宣传渠道使用学生作品。

**5. 您的选择完全自由**

- 同意纯属**自愿**。拒绝不影响报名、课程内容或您子女所获得的任何服务
- 您可**随时撤回同意**，发送电邮至 info@dreamer-aiedu.com 即可
- 撤回后，我们将于 **24 小时内**将学生作品从所有渠道下架

**6. 与 AI 对话功能之关系（解耦声明）**

本同意书仅涵盖学生创作作品之媒体展示，**与平台的 AI 对话教学功能并无关联**。撤回本同意书**不会**影响 AI 对话功能的运作；同样，撤回 AI 对话服务同意书亦不影响本同意书之效力。

**7. 有效期**

本同意书有效期为学生课程期间**加 12 个月**。期满后我们将停止使用相关作品；如需续期，我们将联络您重新签署。

### 同意声明

请在其中一个方框内加上 ✓：

- ☐ 本人**同意** Dreamer AI 按上述方式使用本人子女的创作作品。
- ☐ 本人**不同意** Dreamer AI 使用本人子女的创作作品。

| 项目 | 填写 |
|---|---|
| 学生名字（first name） | ____________________ |
| 家长／监护人姓名 | ____________________ |
| 与学生关系 | ____________________ |
| 签署 | ____________________ |
| 日期 | ____________________ |

---

## 1C. English (en)

### Student Work Media Consent

**1. What this form is about**

Dreamer AI would like to showcase student work — for example avatar artwork, posters, videos, game projects, and portfolio items — in our official marketing channels. This form asks for your permission as the parent or legal guardian. Signing is entirely optional.

**2. What we may use, and where**

With your consent, we may use the student's **creative works** in:

- Our official website (dreamer-aiedu.com)
- Our official Instagram, Facebook, Xiaohongshu (RedNotes), WeChat, and Threads pages
- Printed marketing materials (e.g., brochures, flyers)

**3. How we protect your child's identity — always**

- Under this consent, we use the student's **first name and avatar only**
- We will **never** publish the student's full name, school name, photograph, video of their face, or any contact details, **unless you give separate, specific written approval for that particular use**; you may withdraw that approval at any time, and our 24-hour takedown promise in Section 5 applies
- Works are shown as creative output only, never with assessment grades or internal labels

**4. Approval first**

No student work will ever be used in any marketing channel **unless and until** this consent form is signed by a parent or legal guardian.

**5. Your choice is free**

- Consent is **voluntary**. Refusing will not affect enrolment, course content, or any service your child receives
- You may **withdraw consent at any time** by emailing info@dreamer-aiedu.com
- Upon withdrawal, we will remove the student's works from all our channels **within 24 hours**

**6. Relationship with the AI chat feature (decoupling statement)**

This consent covers **only** the display of the student's creative works as media. It is **separate from** the platform's AI chat tutoring feature. Withdrawing this consent will **not** affect the operation of the AI chat feature; likewise, withdrawing the AI Chat Service Consent will not affect this consent.

**7. Duration**

This consent is valid for the duration of the student's course **plus 12 months**. When it expires, we will stop using the works and contact you if we wish to renew.

### Consent Declaration

Please tick one box:

- ☐ **I CONSENT** to Dreamer AI using my child's creative works as described above.
- ☐ **I DO NOT CONSENT** to Dreamer AI using my child's creative works.

| Field | Entry |
|---|---|
| Student's first name | ____________________ |
| Parent / Guardian full name | ____________________ |
| Relationship to student | ____________________ |
| Signature | ____________________ |
| Date | ____________________ |

---

# 二、AI 對話服務同意書（AI Chat Service Consent）

> 新增 doc_type（W6 解耦決策 D-W6-2）：AI 對話教學功能之獨立授權。
> 與「媒體同意書」互不影響，逐項獨立同意、獨立撤回。

## 2A. 繁體中文（zh-HK · 為準）

### AI 對話服務同意書

**1. 本文件之目的**

Dreamer AI 學習平台提供 AI 導師對話教學功能（下稱「AI 對話功能」），學生可透過文字對話與 AI 導師互動、完成學習任務。本文件向家長或合法監護人說明該功能處理學生資料之方式，並徵求同意。

**2. 我們處理之資料**

使用 AI 對話功能時，我們會處理：

- 學生輸入之對話文字內容
- 系統生成之對話回應，以及為維持對話連續性所需之上文脈絡
- 為保障學生安全而設之自動偵測結果（見私隱政策第 6 條）

**3. 資料之使用及傳輸**

- 對話內容會傳送至第三方 AI 語言模型服務供應商處理，以生成教學回應；相關跨境傳輸安排載於私隱政策第 5 條
- 對話內容**僅**用於提供教學服務及保障學生安全，**絕不**用於廣告、宣傳或出售
- 對話內容不會用作未經匿名化之研究用途

**4. 對話記錄之保留**

- AI 對話記錄保留 **90 日**，其後自動刪除
- 90 日後，對話之上文脈絡將一併重置；重新開始對話時，AI 導師不會擁有先前對話之記憶。此為平台既定之產品安排，用以控制個人資料之保留範圍
- 對話記錄不影響家長報告或作品集之生成（該等報告基於學習記錄，獨立於對話記錄）

**5. 閣下之選擇**

- AI 對話功能為平台核心教學功能之一。若不同意本文件之處理安排，AI 對話功能將無法提供，但不會影響媒體同意書之任何安排
- 閣下可**隨時撤回本同意**，電郵 info@dreamer-aiedu.com 即可；撤回後 AI 對話功能將停止運作
- 撤回本同意**不會**影響媒體同意書之效力；媒體同意書之撤回亦不會影響本同意

**6. 學生安全之例外**

為保障學生安全，即使撤回本同意，如系統偵測到學生表達自我傷害或傷害他人之風險，我們仍會按私隱政策第 6 條採取保障措施，包括通知指定之學生保障負責人及提供求助支援熱線資訊。

### 同意聲明

請於其中一個方格加上 ✓：

- ☐ 本人**同意** Dreamer AI 按上述方式處理本人子女之 AI 對話內容，以提供 AI 對話教學功能。
- ☐ 本人**不同意** Dreamer AI 按上述方式處理本人子女之 AI 對話內容（AI 對話功能將無法使用）。

| 項目 | 填寫 |
|---|---|
| 學生名字（first name） | ____________________ |
| 家長／監護人姓名 | ____________________ |
| 與學生關係 | ____________________ |
| 簽署 | ____________________ |
| 日期 | ____________________ |

---

## 2B. 简体中文（zh-CN · 译文）

### AI 对话服务同意书

**1. 本文件之目的**

Dreamer AI 学习平台提供 AI 导师对话教学功能（下称「AI 对话功能」），学生可通过文字对话与 AI 导师互动、完成学习任务。本文件向家长或合法监护人说明该功能处理学生资料的方式，并征询同意。

**2. 我们处理的资料**

使用 AI 对话功能时，我们会处理：

- 学生输入的对话文字内容
- 系统生成的对话回应，以及为维持对话连续性所需之上文脉络
- 为保障学生安全而设的自动侦测结果（见隐私政策第 6 条）

**3. 资料的使用及传输**

- 对话内容会传送至第三方 AI 语言模型服务供应商处理，以生成教学回应；相关跨境传输安排载于隐私政策第 5 条
- 对话内容**仅**用于提供教学服务及保障学生安全，**绝不**用于广告、宣传或出售
- 对话内容不会用于未经匿名化的研究用途

**4. 对话记录的保留**

- AI 对话记录保留 **90 日**，其后自动删除
- 90 日后，对话之上文脉络将一并重置；重新开始对话时，AI 导师不会拥有先前对话的记忆。此为平台既定的产品安排，用以控制个人资料的保留范围
- 对话记录不影响家长报告或作品集的生成（该等报告基于学习记录，独立于对话记录）

**5. 您的选择**

- AI 对话功能为平台核心教学功能之一。若不同意本文件的处理安排，AI 对话功能将无法提供，但不会影响媒体同意书的任何安排
- 您可**随时撤回本同意**，发送电邮至 info@dreamer-aiedu.com 即可；撤回后 AI 对话功能将停止运作
- 撤回本同意**不会**影响媒体同意书的效力；媒体同意书的撤回亦不会影响本同意

**6. 学生安全之例外**

为保障学生安全，即使撤回本同意，如系统侦测到学生表达自我伤害或伤害他人之风险，我们仍会按隐私政策第 6 条采取保障措施，包括通知指定的学生保障负责人及提供求助支援热线信息。

### 同意声明

请在其中一个方框内加上 ✓：

- ☐ 本人**同意** Dreamer AI 按上述方式处理本人子女的 AI 对话内容，以提供 AI 对话教学功能。
- ☐ 本人**不同意** Dreamer AI 按上述方式处理本人子女的 AI 对话内容（AI 对话功能将无法使用）。

| 项目 | 填写 |
|---|---|
| 学生名字（first name） | ____________________ |
| 家长／监护人姓名 | ____________________ |
| 与学生关系 | ____________________ |
| 签署 | ____________________ |
| 日期 | ____________________ |

---

## 2C. English (en)

### AI Chat Service Consent

**1. What this form is about**

The Dreamer AI learning platform provides an AI tutor chat feature (the "AI Chat Feature") through which students interact with an AI tutor in text and complete learning tasks. This form explains to the parent or legal guardian how the feature processes student data and seeks your consent.

**2. What we process**

When the AI Chat Feature is used, we process:

- The text content of the student's messages
- System-generated responses, and the preceding context needed to maintain conversation continuity
- Automated safety-detection results designed to protect student safety (see Section 6 of the Privacy Policy)

**3. How the data is used and transferred**

- Message content is transmitted to third-party AI language model service providers to generate tutoring responses; the related cross-border transfer arrangements are set out in Section 5 of the Privacy Policy
- Message content is used **solely** to provide the tutoring service and to protect student safety. It is **never** used for advertising, promotion, or sale
- Message content is not used for research without anonymisation

**4. Retention of chat records**

- AI chat records are retained for **90 days** and then automatically deleted
- After 90 days, the preceding conversation context is also reset; when a new conversation begins, the AI tutor will have no memory of earlier conversations. This is the platform's established product arrangement, designed to limit the scope of retained personal data
- Chat records do not affect the generation of parent reports or portfolios (those reports are based on learning records and are independent of chat records)

**5. Your choice**

- The AI Chat Feature is one of the platform's core teaching functions. If you do not consent to the processing described in this form, the AI Chat Feature cannot be provided; this does not affect any arrangement under the Media Consent Form
- You may **withdraw this consent at any time** by emailing info@dreamer-aiedu.com; upon withdrawal, the AI Chat Feature will cease to operate
- Withdrawing this consent will **not** affect the validity of the Media Consent Form; likewise, withdrawing the Media Consent Form will not affect this consent

**6. Student safety exception**

For the protection of student safety, even after withdrawal of this consent, if the system detects that a student expresses a risk of self-harm or harm to others, we will still take protective measures in accordance with Section 6 of the Privacy Policy, including notifying the designated student safeguarding staff member and providing helpline support information.

### Consent Declaration

Please tick one box:

- ☐ **I CONSENT** to Dreamer AI processing my child's AI chat content as described above, in order to provide the AI Chat tutoring feature.
- ☐ **I DO NOT CONSENT** to Dreamer AI processing my child's AI chat content as described above (the AI Chat Feature will be unavailable).

| Field | Entry |
|---|---|
| Student's first name | ____________________ |
| Parent / Guardian full name | ____________________ |
| Relationship to student | ____________________ |
| Signature | ____________________ |
| Date | ____________________ |

---

*Dreamer AI Education Limited · info@dreamer-aiedu.com · dreamer-aiedu.com*

---

# 三、職員資料處理守則（Staff Data Processing Notice · W6 PR-G）

> 對象：`teacher` / `admin` 帳號（registry `roles: ["teacher", "admin"]`）。家長帳號唔會見到本文件，職員帳號亦唔會再被家長文件（privacy / media / chat）擋住。

## 3A. 繁體中文（zh-HK · 為準）

### 職員資料處理守則

**生效日期：2026 年 9 月 10 日**

**1. 本守則嘅目的**

本守則適用於平台所有職員角色嘅帳號（老師、班務行政、學生保護人員）。作為職員，你可以睇到同處理小朋友嘅個人資料 — 姓名、年齡組別、學習紀錄、進度報告同家長聯絡資料。本守則講明你必須點樣處理呢啲資料；簽署本守則，即代表你接受呢啲義務，作為持有職員帳號嘅條件。

**2. 查閱範圍**

- 你只可以查閱你嘅角色同你負責班別所授權嘅學生、班別同紀錄
- 查閱權只限教學、評估、學生保護同家長溝通用途；任何其他用途（包括出於個人好奇）一律禁止
- 職員帳號屬個人專用。登入憑證絕對唔可以共用，你唔可以用其他職員嘅帳號，亦唔可以讓其他人用你嘅帳號

**3. 學生資料嘅處理要求**

- 學生資料只可用於當初收集嘅教育用途
- 唔可以將學生資料或小朋友嘅作品複製、拍攝、截圖或錄影後帶離平台
- 唔可以將學生資料匯出到私人裝置、私人雲端、私人通訊軟件或私人電郵
- 唔可以為私人用途拍攝小朋友，亦絕對唔可以將任何學生嘅影像、作品或可識別身分嘅資料發佈到社交媒體或任何公開渠道
- 除非平台嘅授權流程（例如家長已同意嘅報告）明確涵蓋，否則唔可以向任何第三方披露學生資料，包括其他家長、其他學生或外部導師
- 唔可以將學生資料寫落會離開平台嘅私人筆記；如因運作上無可避免需要線下紀錄，必須安全保存，並喺唔再需要時立即銷毀

**4. 準確、保留同安全**

- 準確記錄資料，並且只記錄其所述教育用途所需嘅內容；如知悉資料有誤，應更正或標示
- 遵守平台嘅保留安排 — 紀錄只會保留到教育用途或法律所需嘅期間，之後會刪除。其後唔可以再保留私人副本
- 上載同溝通一律使用平台本身嘅渠道；唔可以將學生資料轉移到未經批准嘅工具，包括第三方 AI 工具

**5. 學生保護責任**

如你知悉任何學生有自我傷害或受傷害嘅風險，必須立即依從學生保護程序：經指定嘅保護渠道即刻報告，並在適當情況下提供求助熱線資訊。家長嘅任何同意選擇，都唔會取消呢項責任。

**6. 審計同監察**

查閱學生紀錄會被記錄，並可能被審計。如你查閱你無權查閱嘅紀錄，即屬違反本守則，即使你冇複製或分享任何內容。

**7. 如發生事故**

如懷疑有任何資料遺失、未經授權披露、誤發電郵、未經授權查閱或憑證外洩，必須立即（無論如何喺 24 小時內）電郵 info@dreamer-aiedu.com 報告。及早報告既保護小朋友，亦保護你自己。

**8. 違反守則嘅後果**

違反本守則可能導致平台使用權被撤銷，並可能構成紀律及／或合約問題；如法律要求，亦可能向相關機構報告。

### 確認聲明

簽署以下欄位，即確認你已閱讀並理解本守則，並接受本守則所列嘅義務。

| 欄位 | 填寫 |
|---|---|
| 職員全名 | ____________________ |
| 角色（老師／行政／學生保護） | ____________________ |
| 簽名 | ____________________ |
| 日期 | ____________________ |

## 3B. 简体中文（zh-CN · 译文）

### 职员数据处理守则

**生效日期：2026 年 9 月 10 日**

**1. 本守则的目的**

本守则适用于平台所有职员角色的账号（老师、班务行政、学生保护人员）。作为职员，你可以看到并处理孩子的个人资料 — 姓名、年龄组别、学习记录、进度报告和家长联络资料。本守则说明你必须如何处理这些资料；签署本守则，即代表你接受这些义务，作为持有职员账号的条件。

**2. 查阅范围**

- 你只可以查阅你的角色和你负责班别所授权的学生、班别和记录
- 查阅权限于教学、评估、学生保护和家长沟通用途；任何其他用途（包括出于个人好奇）一律禁止
- 职员账号属个人专用。登录凭证绝对不可以共用，你不可以使用其他职员的账号，也不可以让其他人使用你的账号

**3. 学生资料的处理要求**

- 学生资料只可用于当初收集的教育用途
- 不可以将学生资料或孩子的作品复制、拍摄、截图或录影后带离平台
- 不可以将学生资料导出到私人装置、私人云端、私人通讯软件或私人邮箱
- 不可以为私人用途拍摄孩子，也绝对不可以将任何学生的影像、作品或可识别身分的资料发布到社交媒体或任何公开渠道
- 除非平台的授权流程（例如家长已同意的报告）明确涵盖，否则不可以向任何第三方披露学生资料，包括其他家长、其他学生或外部导师
- 不可以将学生资料写进会离开平台的私人笔记；如因运作上无可避免需要线下记录，必须安全保存，并在不再需要时立即销毁

**4. 准确、保留和安全**

- 准确记录资料，并且只记录其所述教育用途所需的内容；如知悉资料有误，应更正或标示
- 遵守平台的保留安排 — 记录只会保留到教育用途或法律所需的期间，之后会删除。其后不可以再保留私人副本
- 上传和沟通一律使用平台本身的渠道；不可以将学生资料转移到未经批准的工具，包括第三方 AI 工具

**5. 学生保护责任**

如你知悉任何学生有自我伤害或受伤害的风险，必须立即依从学生保护程序：经指定的保护渠道即时报告，并在适当情况下提供求助热线资讯。家长的任何同意选择，都不会取消这项责任。

**6. 审计和监察**

查阅学生记录会被记录，并可能被审计。如你查阅你无权查阅的记录，即属违反本守则，即使你没有复制或分享任何内容。

**7. 如发生事故**

如怀疑有任何资料遗失、未经授权披露、误发邮件、未经授权查阅或凭证外泄，必须立即（无论如何在 24 小时内）发送邮件至 info@dreamer-aiedu.com 报告。及早报告既保护孩子，亦保护你自己。

**8. 违反守则的后果**

违反本守则可能导致平台使用权被撤销，并可能构成纪律及／或合约问题；如法律要求，亦可能向相关机构报告。

### 确认声明

签署以下栏位，即确认你已阅读并理解本守则，并接受本守则所列的义务。

| 栏位 | 填写 |
|---|---|
| 职员全名 | ____________________ |
| 角色（老师／行政／学生保护） | ____________________ |
| 签名 | ____________________ |
| 日期 | ____________________ |

## 3C. English (en)

### Staff Data Processing Notice

**Effective Date: 10 September 2026**

**1. What this notice is about**

This notice applies to every platform account with a staff role (teacher, class administrator or safeguarding staff member). As a member of staff you can see and handle children's personal data — names, age bands, learning records, progress reports and parent contact details. This notice sets out how you must handle that data, and by signing it you accept those obligations as a condition of your staff account.

**2. Scope of access**

- You may access **only** the students, classes and records that your role and your assigned classes entitle you to
- Access is granted for teaching, assessment, safeguarding and parent-communication purposes only. Any other use — including satisfying personal curiosity — is prohibited
- Staff accounts are personal. Log-in credentials must never be shared, and you must not use another staff member's account or let anyone use yours

**3. How you must handle student data**

- Use student data only for the educational purpose for which it was collected
- Do not copy, photograph, screen-capture or screen-record student data or children's work outside the platform
- Do not export student data to personal devices, personal cloud storage, personal messaging apps or personal email
- Do not photograph or film children for personal use, and never publish images, work or identifying details of any student on social media or any other public channel
- Do not disclose student data to any third party, including other parents, other students or external tutors, unless the platform's authorisation flow (for example a parent-consented report) explicitly covers it
- Keep student data out of personal notes that leave the platform; if an offline record is operationally unavoidable, store it securely and destroy it as soon as it is no longer needed

**4. Accuracy, retention and security**

- Record information accurately and only as needed for its stated educational purpose; correct or flag anything you know to be wrong
- Follow the platform's retention arrangements — records are kept only as long as the educational purpose or the law requires, and are then deleted. Do not keep private copies after that point
- Use the platform's own channels for uploads and communication; do not move student data onto unapproved tools, including third-party AI tools

**5. Safeguarding duty**

If you become aware of any risk of self-harm or harm to a student, follow the safeguarding protocol immediately: report it through the designated safeguarding route without delay and provide helpline support information where appropriate. A consent choice by a parent never cancels this duty.

**6. Audit and monitoring**

Access to student records is logged and may be audited. If you access a record you are not entitled to access, this notice is breached, even if nothing is copied or shared.

**7. If something goes wrong**

Report immediately — and in any event within 24 hours — any suspected loss, unauthorised disclosure, misdirected email, unauthorised access or credential compromise to info@dreamer-aiedu.com. Early reporting protects the children and protects you.

**8. Consequences of breach**

Breach of this notice may result in withdrawal of platform access and may be treated as a disciplinary and/or contractual matter, and may be reported to the relevant authority where the law requires.

### Acknowledgement

By signing below you confirm that you have read and understood this notice and that you accept the obligations it sets out.

| Field | Entry |
|---|---|
| Staff full name | ____________________ |
| Role (teacher / admin / safeguarding) | ____________________ |
| Signature | ____________________ |
| Date | ____________________ |

---

*Dreamer AI Education Limited · info@dreamer-aiedu.com · dreamer-aiedu.com*
