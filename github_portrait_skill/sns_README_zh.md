# SNS 写实人像提示词导演

[繁體中文](README.zh-TW.md) · **简体中文** · [日本語](README.ja.md) · [English](README.md)

这是一个 Agent Skill，可将简短的人像画面构想转换为适用于 Midjourney、Stable Diffusion、Nano Banana 和 GPT Image 2 的纯英文写实摄影提示词。

它优先追求如真实社交媒体动态般自然可信的照片感：生活痕迹、自然肤质、一致光影、非摆拍表情与正确的平台格式，而不是华丽却明显 AI 化的视觉效果。

## 核心能力

- 支持不同性别、年龄和多人组合的虚构人物肖像。
- 从 30 项写实技巧中，每次只精选最相关的 3–5 项。
- 可输出四段式人类可读格式，或严格可解析的 JSON。
- 自动区分 Midjourney、Stable Diffusion、Nano Banana 和 GPT Image 2 的提示词格式。
- 儿童和青少年可用于正常、符合年龄且非性化的日常人像。
- 提供针对场景的避坑建议，而不是堆砌空泛质量词。

## 快速开始

输入人物、动作、场景、用途和平台即可：

```text
Midjourney：六十多岁男性在咖啡店看窗外，适合 Instagram，右侧留文案空间
```

如需机器可读结果，加入 `JSON`、`API`、`结构化` 或 `机器可读`：

```text
Nano Banana 2，JSON：九岁小孩穿雨衣在住宅区踩水洼，像家人随手拍
```

## 默认输出格式

未指定 JSON 时，Skill 用繁体中文提供解析与指引，并给出纯英文 prompt：

1. **【场景美学解析】**：画面如何兼顾真实感和 SNS 吸引力。
2. **【本次启用的 SKILL】**：列出本次精选的 3–5 项技巧。
3. **【复制即用提示词】**：可直接使用的英文提示词。
4. **【大师级避坑指引】**：一个具体、可操作的微调建议。

## 支持模型与格式规则

| 目标模型 | 输出规则 |
|---|---|
| Midjourney | 需要 3:4 时，将 `--ar 3:4` 放在英文 prompt 最末尾。 |
| Stable Diffusion／SDXL／SD 3.x | 不将 Midjourney 参数写入 prompt；比例在 UI/API 中设置，必要时才加简短负向提示。 |
| Nano Banana | 使用完整自然语言指令；支持 Nano Banana、Nano Banana Pro、Nano Banana 2。 |
| GPT Image 2 | 使用清晰分层的自然语言；支持 Image 2、image2、GPT Image 2、`gpt-image-2`。 |

> JSON 是本 Skill 的工作流封装格式，不代表目标图像模型原生支持 Structured Outputs。

## 使用原则

1. 自然感优先于华丽感。
2. 描述可见细节，不堆叠 `masterpiece`、`8K`、`perfect face` 等空泛词。
3. 光源、阴影、背景与姿势必须能存在于同一个可拍摄场景。
4. 手入镜时才针对手部与物件接触进行描述。
5. 未明确说明时，不自行补充性别、年龄、族裔或人物关系。
6. 未成年人只处理符合年龄、非性化的内容。

## 安装方式

将整个文件夹放入 Agent 项目的技能目录：

```text
.agents/skills/sns-realistic-portrait-prompt/
```

入口文件是 `SKILL.md`；请保留同层的 `references/`，因为 Skill 会按需读取模型格式、JSON 契约、示例和技巧矩阵。

## 文件结构

```text
.
├── SKILL.md                         # 执行规则与输出契约
├── MANUAL.md                        # 详细繁体中文使用手册
├── SPEC.md                          # 范围、维护与验收条件
├── SOURCES.md                       # 来源与决策记录
└── references/
    ├── technique-matrix.md          # 30 项写实技巧
    ├── platform-adaptation.md       # 各模型格式差异
    ├── json-output-contract.md      # JSON schema 与示例
    └── transformed-examples.md      # 成功、稳健与反例修正
```

## 扩展文档

- [详细使用手册（繁体中文）](MANUAL.md)
- [执行规则](SKILL.md)
- [模型格式差异](references/platform-adaptation.md)
- [JSON 输出契约](references/json-output-contract.md)
- [30 项技巧矩阵](references/technique-matrix.md)

## 限制

纯文本提示可以降低手部、文字、遮挡和多人透视错误，但无法保证完全不出错。模型名称、可用比例和 API 会持续更新，正式集成前请再次核对平台官方文档。
