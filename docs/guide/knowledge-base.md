# Knowledge base

> **🇬🇧 English** · [🇨🇳 中文](../i18n/zh-CN/guide/knowledge-base.md) · [🇫🇷 Français](../i18n/fr/guide/knowledge-base.md) · [🇪🇸 Español](../i18n/es/guide/knowledge-base.md) · [🇵🇹 Português](../i18n/pt/guide/knowledge-base.md) · [🇮🇹 Italiano](../i18n/it/guide/knowledge-base.md) · [🇩🇪 Deutsch](../i18n/de/guide/knowledge-base.md) · [🇳🇴 Norsk](../i18n/nb/guide/knowledge-base.md)

ekte judges a relay against the **profile** of the model it claims: native
context window, max output, knowledge cutoff, tokenizer, capability flags,
identity keywords and behavioral fingerprints. The packaged profiles cover
OpenAI, Anthropic, Google Gemini, DeepSeek, Qwen, GLM and Moonshot
(`ekte kb` lists them). There are three layers, later ones winning:

1. **Packaged** profiles, one YAML file per provider in
   [`ekte/knowledge/data/`](../../ekte/knowledge/data).
2. **A directory of your own YAML files**: `--kb-dir ./my-profiles` (repeatable)
   or `EKTE_KB_DIR`.
3. **Your entries** (`kb.db` in the data directory), added without YAML files
   or an editable install:
   - in the web UI's **Knowledge** page (`/kb`), with one tab each for
     **Models**, **Providers** and **Relays**. Every tab lists the complete set —
     packaged, `EKTE_KB_DIR` and yours (marked **Yours**) — with a filter, an
     on/off switch per item and an **Add …** form: **Add a model** → **Copy the
     research prompt** into the AI assistant of your choice, upload or paste the
     YAML it answers with, then **Check and save**; **Add a provider** takes
     provider YAML the same way; **Add a relay** takes a name and a base URL.
     **Which profile does a model id use?** shows how an id resolves; your
     entries can be exported as YAML;
   - on the web UI's **Audit** page: **Save to knowledge base**
     keeps a relay's name and base URL (a provider entry without models), listed
     under **Knowledge → Relays**;
   - on the CLI: `ekte kb-prompt <model>`, `ekte kb-import <file>` (add `--check`
     to only check it) and `ekte kb-export`.

Before storing an entry ekte checks it: schema and limits, unsafe regular
expressions, every prompt it would send, and model ids that would resolve to a
different profile. A model of yours with a packaged id replaces it (reported as
*shadowing* it), but never changes a packaged provider's own settings;
fingerprints are merged by id. Switching off a packaged model, provider or
relay on the **Knowledge** page is stored in `kb.db` too: a switched-off model
id no longer resolves, a switched-off provider takes its models and base URLs
with it. `ekte check` and `ekte serve` use exactly the same profiles;
`--no-user-kb` (or `EKTE_NO_USER_KB=1`) leaves your entries and switches out.

A model whose `identity_keywords` is empty is not stored that way: ekte fills
in its own brand words from the provider and model names (for example `glm`
and `z.ai`) and shows a warning to check them, since
without them the identity check could take the model naming its own vendor for
a rival brand. The research prompt asks the AI assistant for them explicitly.

Every report records the profile it audited against (`knowledge`: provider,
model, how the id matched, its source, and a full snapshot with its content
hash), so a report stays verifiable after the knowledge base changes.
