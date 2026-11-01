# 知识库

> [🇬🇧 English](../../../guide/knowledge-base.md) · **🇨🇳 中文** · [🇫🇷 Français](../../fr/guide/knowledge-base.md) · [🇪🇸 Español](../../es/guide/knowledge-base.md) · [🇵🇹 Português](../../pt/guide/knowledge-base.md) · [🇮🇹 Italiano](../../it/guide/knowledge-base.md) · [🇩🇪 Deutsch](../../de/guide/knowledge-base.md) · [🇳🇴 Norsk](../../nb/guide/knowledge-base.md)

ekte 依据所声称模型的**画像**来评判中转站：原生上下文窗口、最大输出、知识截止日期、分词器、
能力标记、身份关键词和行为指纹。内置画像覆盖 OpenAI、Anthropic、Google Gemini、DeepSeek、
Qwen、GLM 和 Moonshot（用 `ekte kb` 查看）。共有三层，后面的优先：

1. **内置**画像，每个厂商一个 YAML 文件，位于 [`ekte/knowledge/data/`](../../../../ekte/knowledge/data)。
2. **你自己的 YAML 目录**：`--kb-dir ./my-profiles`（可重复）或 `EKTE_KB_DIR`。
3. **你的条目**（数据目录中的 `kb.db`），无需 YAML 文件或可编辑安装即可添加：
   - 在 Web 界面的**知识库**页面（`/kb`），分为**模型**、**厂商**、**中转站**三个标签页。每个标签页
     列出完整集合——内置的、`EKTE_KB_DIR` 的和你的（标记为**你的**）——提供筛选、每项的启用/停用开关
     和**添加…**表单：**添加模型** → **复制调研提示词**，粘贴到你选用的 AI 助手中，上传或粘贴它回复的
     YAML，然后**检查并保存**；**添加厂商**以同样方式接收厂商 YAML；**添加中转站**只需名称和基础地址。
     **某个模型 ID 会使用哪份资料？**显示某个 id 如何解析；你的条目可导出为 YAML；
   - 在 Web 界面的**检测**页面：**保存到知识库**会保存中转站的名称和基础地址（一个不含模型的
     厂商条目），列在**知识库 → 中转站**中；
   - 在命令行：`ekte kb-prompt <model>`、`ekte kb-import <file>`（加 `--check` 只检查不保存）
     和 `ekte kb-export`。

保存条目前 ekte 会先检查：结构与限制、不安全的正则表达式、它将发送的每条提示词，以及会解析到
其他画像的模型 id。你的模型若与内置模型 id 相同，会替换内置模型（报告为*遮蔽*了它），但绝不会
修改内置厂商自身的设置；指纹按 id 合并。在**知识库**页面停用内置模型、厂商或中转站同样保存在
`kb.db` 中：停用的模型 id 不再参与解析，停用的厂商会连同其模型和基础地址一起停用。`ekte check`
与 `ekte serve` 使用完全相同的画像；`--no-user-kb`（或 `EKTE_NO_USER_KB=1`）会排除你的条目和开关。

`identity_keywords` 为空的模型不会原样保存：ekte 会根据厂商与模型名称补上它自己的品牌词
（例如 `glm` 和 `z.ai`），并显示一条警告提醒你核对；没有这些词，身份检查
可能把模型说出的自家厂商当成竞品品牌。研究提示词也会明确要求 AI 助手给出这些词。

每份报告都会记录它对照的画像（`knowledge`：厂商、模型、id 如何匹配、来源，以及带内容哈希的
完整快照），因此即使知识库之后发生变化，报告依然可以核验。
