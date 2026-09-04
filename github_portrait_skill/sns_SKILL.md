---
name: sns-realistic-portrait-prompt
description: 將不同性別、年齡與人物組合的簡單人像構想轉化為自然、寫實、低 AI 塑料感且適合 SNS 發布的純英文 Midjourney、Stable Diffusion、Nano Banana 或 GPT Image 2 攝影提示詞，並可選擇人類可讀格式或嚴格 JSON。當使用者要求寫實人物肖像、男性／女性／兒童／長者／非二元人物或群像、真人感照片、手機隨手拍、Instagram／Threads／X 配圖、Nano Banana／Image 2 prompt、JSON prompt、去除 AI 感、修正人像破綻或優化既有人像 prompt 時使用。
---

# SNS 寫實人像提示詞導演

把使用者的簡單構想轉成具體、可拍攝、自然可信的英文攝影提示詞。以真實感優先於華麗感；不要把技巧清單機械堆進提示詞。

## 每次執行

1. 從輸入抽取主體、動作、神情、場景、服裝、光線、構圖、SNS 用途、模型與輸出格式。
2. 資訊不足時做保守假設，不中斷創作：預設虛構人物但不擅自指定性別或年齡，採自然日常場景、3:4 直幅、非名人、非廣告式擺拍。
3. 從 `references/technique-matrix.md` 精選 3–5 項。至少包含：
   - 1 項真實存在感或照片感（①–⑩）
   - 1 項與場景風險直接相關的防崩壞或品質控制（⑪–⑮、㉖–㉚）
   - 1 項氛圍或 SNS 目標（⑯–㉕）
4. 只啟用會改變本次描述的技巧；手不入鏡時不要選 ⑪，沒有文字需求時不要選 ㉔。
5. 先寫可見事實，再寫攝影語言。使用具體細節取代空泛品質詞；最多使用一組相機／鏡頭描述。
6. 檢查人物、背景、光源、陰影與景深是否屬於同一個可拍攝場景。
7. 判斷輸出格式：使用者明示 JSON、API、結構化或機器可讀時採 JSON；否則採四段式人類可讀格式。
8. 依選定格式輸出，不加前言或結語。

## 提示詞規則

- 英文提示詞依序包含：核心主體、動作與神情、場景與生活細節、構圖、光線與照片質感。
- 用自然微不對稱、真實膚理、細碎髮絲、布料褶皺、環境互動等可見線索表達真實感。
- 避免 `perfect face`、`flawless skin`、`8K ultra detailed masterpiece`、`CGI`、`doll-like` 等容易製造蠟像感或無法驗證的堆詞。
- 不以國籍或族裔推導五官；只有使用者明示時才描述相關外觀。
- 只有使用者明示或場景不可避免時才指定性別、年齡、性別表達或人物關係；未指定時使用 `a fictional person`、`a fictional group of people` 等中性描述。
- 不聲稱能保證零畸變。把風險寫成可觀察的構圖或細節要求，並在避坑指引提供一個可操作修正。
- 若使用者提供真人姓名、照片或要求複製真人長相，改為非識別性的視覺特徵與氛圍，不承諾精確身份複製。
- 可處理兒童與青少年正常、非性化的人像；服裝、姿勢、妝容、場景與鏡頭語言必須符合其年齡。拒絕任何未成年人或年齡不明人物的性化呈現。

## 平台處理

當模型未指定時，輸出 Midjourney 版本。需要精確處理模型差異時，讀取 `references/platform-adaptation.md`。

- Midjourney：在英文提示詞末尾加 `--ar 3:4`，參數前不加逗號。
- Stable Diffusion：提示詞本身不加入 `--ar`；在同一程式碼區塊另列精簡的 `Negative prompt:`，並在避坑指引提醒將畫布設為 3:4。
- Nano Banana：接受 `Nano Banana`、`Nano Banana Pro`、`Nano Banana 2` 與正式 Gemini model ID；採完整自然語言指令，不加入 Midjourney 參數或關鍵詞式 negative prompt。
- GPT Image 2：接受 `Image 2`、`GPT Image 2`、`image2` 與 `gpt-image-2`；採明確的自然語言場景指令，不加入 Midjourney 參數。
- 使用者要求多模型版本時，在【複製即用提示詞】內清楚標出各模型；其他三段維持一次即可。

## JSON 輸出

使用者要求 JSON 時，讀取 `references/json-output-contract.md`，並以該檔的固定 schema 取代下方四段式格式。

- 只輸出一個有效 JSON object，不使用 Markdown code fence、註解或尾逗號。
- JSON 字串內換行與引號必須正確跳脫。
- `prompt_en` 保持純英文；分析、技巧名稱與指引使用繁體中文欄位。
- `model` 使用正式 model ID；別名解析規則見 `references/platform-adaptation.md`。
- JSON 是技能回覆格式，不代表目標圖像模型本身支援 Structured Outputs。

## 固定輸出格式

**【場景美學解析】**  
用 2–3 句繁體中文說明真實感來源、畫面焦點與 SNS 吸睛方式。

**【本次啟用的 SKILL】**  
列出 3–5 個編號與短名稱，例如：`啟用技巧 ④ 自然瞬間 + ⑦ 淺景深 + ⑭ 光影一致 + ㉔ 商業留白`。列出的每一項都必須在提示詞中有對應語意。

**【複製即用提示詞】**  
只在程式碼區塊內放英文提示詞與必要的英文平台標籤。不要在提示詞內混入中文解釋。

**【大師級避坑指引】**  
用繁體中文提供一個針對本場景、可立即執行的生成或微調建議；不要重複技巧清單。

## 最終檢查

- 四個標題齊全且順序正確。
- 解析與避坑指引為繁體中文；提示詞為英文。
- 精選技巧為 3–5 項，且與提示詞逐項對應。
- 主體為虛構人物；性別與年齡只在使用者提供時出現，未成年人內容符合年齡且非性化。
- 沒有互相衝突的光源、鏡頭、視線或動作。
- Midjourney 參數只出現在末尾；Stable Diffusion 不含 Midjourney 參數。
- Nano Banana 與 GPT Image 2 使用自然語言指令且不含 `--ar`。
- 自然感優先於華麗感，沒有品質堆詞或塑料美肌措辭。

若採 JSON，以上第一項改為：JSON 可直接解析、schema 欄位完整、沒有 code fence 或額外文字。

## 按需參考

| 需要決定或處理 | 讀取 |
|---|---|
| 從 30 項技巧挑選最適合的 3–5 項 | `references/technique-matrix.md` |
| 判斷 Midjourney、Stable Diffusion、Nano Banana 與 GPT Image 2 的輸出差異 | `references/platform-adaptation.md` |
| 使用者要求 JSON、API 或機器可讀格式 | `references/json-output-contract.md` |
| 校準成品品質、穩健版本或修正堆詞反例 | `references/transformed-examples.md` |
