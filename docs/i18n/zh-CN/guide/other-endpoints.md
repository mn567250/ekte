# Embedding、rerank、图像与音频检测

> [🇬🇧 English](../../../guide/other-endpoints.md) · **🇨🇳 中文** · [🇫🇷 Français](../../fr/guide/other-endpoints.md) · [🇪🇸 Español](../../es/guide/other-endpoints.md) · [🇵🇹 Português](../../pt/guide/other-endpoints.md) · [🇮🇹 Italiano](../../it/guide/other-endpoints.md) · [🇩🇪 Deutsch](../../de/guide/other-endpoints.md) · [🇳🇴 Norsk](../../nb/guide/other-endpoints.md)

这些端点返回的是向量、排序、图像或音频，而不是对话，因此 ekte 用专门的探测而不是对话提示词来审计。
每个都会输出结论，并支持 `--json` 和 `--fail-on-risk`。

## 接口类型（surface）、嵌入与重排监控

每次审计、每条历史记录和每个监控都有一个**接口类型**（`surface`）：`chat`（默认）、`embedding`
或 `rerank`，与测试套件相互独立。嵌入与重排审计和对话审计走同一个 runner、同一套评分（0–100、A–F）、
检测历史、分析和监控，只是检测器不同。检测历史和分析可按接口类型筛选，分析只显示适用的指标。

要监控嵌入或重排端点，先在**检测**页面审计它（在接口类型选择器中选**嵌入**或**重排**），然后选择**监控此端点**，或在检测历史中该行选择
**设为监控**。监控按计划重新审计，知识库固定、告警阈值和回退告警与对话监控相同，并对照上一次运行检查
**漂移**（嵌入探测的向量，重排探测的排序和分数）。嵌入监控的声称维度可以在其卡片上修改（留空或 0：
取自知识库）。速度探测（嵌入：延迟、冷启动、输入/秒、批量扩展；重排：延迟、冷启动、文档/秒、4 与 32
个文档对比）只在 deep、full 或 custom 套件下运行，或在有基线的 standard 下运行。

## Embedding 与 rerank

```bash
# 期望的向量维度会根据声称的模型从知识库中解析。
ekte embed --base-url https://relay.example.com/v1 \
           --model text-embedding-3-large --claimed-model text-embedding-3-large --fail-on-risk high

# 或直接指定期望维度：
ekte embed --base-url ... --model my-embed --claimed-dimensions 1024 --json

# Rerank：内置一个答案已知的探测——真正的 reranker 必须把明显相关的文档排在第一。
ekte rerank --base-url https://relay.example.com/v1 --model my-rerank

# 更深入：加上重排速度探测；--no-save 让这次运行不进入检测历史。
ekte rerank --base-url ... --model my-rerank --suite deep --no-save
# 先查看检查项和预计调用次数，不发送任何请求：
ekte rerank --base-url ... --model my-rerank --dry-run
```

`rerank` 检查连通性、**已知答案探测**（明显相关的文档必须排第一）、回包中的 `model` 字段、确定性
（同一查询两次得到相同的排序和分数）以及相对上一次已保存运行的**排序漂移**。`ekte embed` 和
`ekte rerank` 都支持 `--suite`、`--save/--no-save`（默认保存，下一次运行才有漂移参照）和 `--dry-run`。

`embed` 检查连通性、**维度匹配**（返回向量的长度 vs 声称模型的原生维度——最核心的
“货不对板”信号：声称是 3072 维 `text-embedding-3-large`、却返回 1024 维的中转站，提供的是替代品）、
确定性（相同输入 → 余弦 ≈ 1）、区分度（无关输入 → 余弦明显小于 1）以及回包中的 `model` 字段。
内置画像：OpenAI `text-embedding-3-small`（1536）、`text-embedding-3-large`（3072）、
`text-embedding-ada-002`（1536），Qwen `text-embedding-v3`/`-v4`（1024），Google `gemini-embedding-2`（3072）。

两者在 Web 界面中也可使用：从**检测**页面的接口类型选择器开始（**嵌入**、**重排**）。重排审计始终使用内置探测，
这样每次运行在漂移检查和监控中都可以相互比较。

## 图像与音频（TTS）生成

图像生成（`POST /v1/images/generations`）和文本转语音（`POST /v1/audio/speech`），
只用 Python 标准库解码——从文件头字节读取图像尺寸（PNG/JPEG/GIF/WebP），用 `wave` 读取 WAV 时长。

```bash
# 声称是 DALL·E 3 的中转真的返回了所请求的 1792x1024 吗？被缩小 / 尺寸错误的图像
# （或尺寸不在知识库中声称模型的原生尺寸内）就是最核心的“货不对板”信号。
ekte image --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
  --model dall-e-3 --claimed-model dall-e-3 --size 1792x1024 --fail-on-risk high

# 声称是 tts-1-hd 的中转返回的是时长随输入增长的真实音频吗
# （而不是固定的占位音频，也不是伪装成音频的 HTML/JSON）？
ekte audio --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
  --model tts-1-hd --voice alloy --audio-format wav --save-to clip.wav
```

`image` 检查连通性、格式有效且可解码、**尺寸匹配**（解码出的宽 × 高 vs 请求尺寸和声称模型的
原生尺寸——不匹配即 FAIL/HIGH）、区分度（两个提示词 → 不同的图像，识破固定占位图）、数量以及
`model` 字段。`audio` 检查连通性、容器/格式有效性、格式是否被遵守、随输入增长的非平凡时长、
区分度以及 `model` 字段。知识库包含 OpenAI DALL·E 2/3、gpt-image-1、gpt-image-2、
tts-1/tts-1-hd/gpt-4o-mini-tts，以及 Qwen 的图像/TTS 画像。
