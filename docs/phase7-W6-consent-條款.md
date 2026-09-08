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
