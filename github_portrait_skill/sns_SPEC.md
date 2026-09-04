# SNS Realistic Portrait Prompt Specification

## Intent

把簡單人像構想穩定轉化為自然、可信、適合社群發布的英文攝影提示詞，並以少量、針對性的技巧降低塑料感、擺拍感與常見結構破綻。

## Scope

In scope:

- 不同性別、年齡與人物組合的虛構人物 Midjourney、Stable Diffusion、Nano Banana 與 GPT Image 2 寫實攝影提示詞
- SNS 貼文、頭像、封面與商業留白構圖
- 對既有提示詞去塑料感、去堆詞與平台格式修正
- 可解析 JSON prompt 封裝與多模型 variants

Out of scope:

- 未成年人或年齡不明人物的性化、成人化或不合年齡內容
- 精確複製真人身份或名人長相
- 保證模型不會產生任何解剖或構圖缺陷
- 實際生成、後製或模型參數調優服務

## Users And Trigger Context

- Primary users: 社群創作者、品牌主理人、AI 圖像使用者
- Common user requests: 寫實人像 prompt、男性／女性／兒童／長者／非二元人物或群像、手機隨手拍、Nano Banana／Image 2 prompt、JSON prompt、去 AI 塑料感、人像 prompt 優化
- Should not trigger for: 非人像圖、純插畫／動漫風格、一般攝影器材諮詢

## Runtime Contract

- Required first actions: 抽取場景需求；只採用使用者明示的性別與年齡；確認模型與輸出格式；精選 3–5 技巧
- Required outputs: 四段式人類可讀格式或符合 schema 的單一 JSON object
- Non-negotiable constraints: 自然感優先；不用空泛品質堆詞；平台參數不可混用
- Expected bundled files loaded at runtime: 依需求讀取四個 `references/` 直屬檔案

## Source And Evidence Model

Authoritative sources:

- 使用者提供的 30 技巧與輸出要求
- Midjourney 官方參數文件
- Stability AI 官方 API 文件
- Google Gemini API Nano Banana 官方文件
- OpenAI GPT Image 2 官方模型文件

Useful improvement sources:

- positive examples: 成功的自然人像輸出
- negative examples: 塑料膚質、光影不一致、手部錯誤、提示詞堆疊
- validation results: 結構驗證與人工觸發測試

Data that must not be stored:

- 私人照片、未授權身份資料、秘密或客戶識別資訊

## Reference Architecture

- `SKILL.md` contains: 每次執行的流程、平台預設、輸出契約與檢查
- `references/` contains: 技巧矩陣、平台適配、JSON 契約、轉化範例
- `references/evidence/` contains: 無；未提供真實迭代案例
- `scripts/` contains: 無；此技能不需要自動化
- `assets/` contains: 無

## Validation

- Lightweight validation: frontmatter、路徑、引用檔存在性
- Deeper validation: 四段或 JSON schema、3–5 技巧逐項對應、人物多樣性、未成年人年齡適配、模型格式、反堆詞檢查
- Holdout examples: 男性長者、兒童家庭快拍、非二元人物、多人群像、頭像留白、模型未指定、Nano Banana、GPT Image 2、多模型 JSON
- Acceptance gates: 人類可讀格式標題完整或 JSON 可解析；語言正確；模型參數不混用；沒有互相衝突的攝影描述

## Known Limitations

- 不同 Stable Diffusion 模型與介面對權重和 negative prompt 的支援不同。
- JSON 是技能輸出封裝，不保證目標圖像模型原生支援 Structured Outputs。
- 純文字提示只能降低而不能消除手部、文字與複雜遮擋錯誤。

## Maintenance Notes

- When to update `SKILL.md`: 輸出格式、平台預設或安全範圍改變時
- When to update `SOURCES.md`: 官方參數或來源版本改變時
- When to update `references/evidence/`: 收到可重現的正／負／修正案例時
