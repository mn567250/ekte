# Maintaining the knowledge base

## Editing the knowledge base

Profiles live in `ekte/knowledge/data/<provider>.yaml`, one file per provider.
Each model carries its native context window, max output, knowledge cutoff,
tokenizer, modalities, capability flags, unsupported parameters, identity
keywords and fingerprints (see `ekte/knowledge/schema.py`). When you change a
numeric field, **cite an authoritative source** (the provider's official model
card, pricing or docs) in the pull request: a wrong value causes false positives
against honest relays. `ekte kb-import --check <file>` runs the same checks as
the user import (schema, limits, unsafe regular expressions, prompts, id
collisions).

Provider-level `fingerprints` run on every model of the provider. A probe whose
expectation holds only for some models (a knowledge cutoff, a Pro-tier recall
check, a reasoning trap) belongs in those models' own `fingerprints`, or a
truthful answer from another model counts as a divergence.

Always fill `identity_keywords` with the vendor and model-family words the
model uses for itself. The identity check also counts the provider key, the
display name and the model id as the genuine brand, widened to the vendor's
other names in `VENDOR_BRANDS` (`ekte/knowledge/identity.py`, which is also the
detector's rival-brand list); the import fills empty keywords from these names
with a warning. Add a new vendor's brand words there as one group.

## Model-specific fingerprints

Most of what the identity check runs holds for every model of a vendor: the
self-identification, the provider-level fingerprints and often the knowledge
cutoff. Only a model's own pure-code fingerprints (in the model's
`fingerprints`, `pure_code_checkable: true`, `max_tokens` at most 512) can
tell it from a cheaper sibling, so a relay serving `gpt-4o-mini` for `gpt-4o`
passes everything else. The detector runs a model's own probes before the
provider's, records how many answered as `model_specific_checks`, and when
that is 0 (and no baseline or judge was used) reports
`model_identity.model_specific`: the vendor is consistent, the model was not
verified. `test_chat_profiles_without_a_model_specific_fingerprint_do_not_grow`
in `tests/test_knowledge.py` pins, per provider, how many chat profiles have
none; lower the number when you add one, it must never rise.

The knowledge cutoff needs no fingerprint: the detector asks every model whose
`knowledge_cutoff` is `YYYY-MM` or `YYYY-MM-DD` for `CUTOFF=YYYY-MM` and
compares the answer (methodology, `model_identity.cutoff`). Write the cutoff in
that form when the provider documents the month; a vague value ("~2025",
"not officially published") switches the probe off for that model, which is
better than a guessed month.

Adding a model-specific fingerprint:

1. **Find a separating behaviour** on the model's official documentation or by
   experiment: a fact, format or reasoning step the genuine model gets right
   and its cheaper siblings do not. The answer must fit in 512 tokens and be
   checkable with `expect_contains`, `expect_contains_any`,
   `expect_not_contains` or `expect_regex`. `expect_contains` and
   `expect_contains_any` match substrings; `expect_not_contains` terms match
   whole words (`helpers.contains_term`: `meta` is not in `metadata`, `qwen`
   is in `Qwen2.5`, CJK and token-like terms such as `<|User|>` still match
   inside text).
2. **Measure it against the genuine model** through the provider's own API
   (not a relay) at the probe's `temperature`, several times, and against each
   sibling you want it to separate. Keep the probe only if the genuine model
   meets the expectation every time and the siblings miss it. Never commit an
   expectation you have not measured: a wrong one makes honest relays diverge.
3. **Record the measurement** on the probe: `separates_from` lists the sibling
   ids that missed it, `verified` the ISO date of the measurement (required
   with `separates_from`). Both appear in the finding's evidence. In the pull
   request, give the provider, the model ids, the dates and the raw answers.
4. Put the probe in the model's own `fingerprints`, never in the provider's,
   and lower the model's provider in `_WITHOUT_MODEL_SPECIFIC`.

```yaml
- id: gpt-4o
  knowledge_cutoff: "2023-10"
  fingerprints:
    - id: example-separating-probe
      signal: example separating behaviour
      prompt: "..."
      pure_code_checkable: true
      expect_contains: ["..."]
      max_tokens: 64
      separates_from: [gpt-4o-mini]
      verified: "2026-11-01"
```

In compare mode every fingerprint also goes to the trusted baseline. A probe
that the baseline misses too is reported as `baseline_also_diverged` (Info, no
deduction): that is a knowledge-base bug, so fix or remove the probe.

## Keeping the knowledge base current

Provider and model data ages quickly, and every verdict depends on it, so ekte
is honest about how old it is. Each packaged provider profile carries
`last_verified`, the date its data was last checked against the provider's
documentation. The oldest of these dates is the **knowledge-base date**: it is
stored in every report (`knowledge.kb_date`), shown by `ekte kb` and in the
Markdown, HTML and PDF reports, and exposed by `ekte kb --json`. When it is
older than `STALE_AFTER_DAYS` (180 days, in `ekte/knowledge/freshness.py`),
the report gets a warning that points to updating ekte or adding your own
entries. The warning never changes the verdict.

The update process:

- **Sources.** Only official provider pages: the model list and model cards,
  pricing and limits pages, the deprecation and retirement notices and the
  release notes. Record the link in the pull request.
- **Who.** The maintainers. Anyone can propose a change with the
  "Knowledge base update" issue form (provider, model id, change, source link
  and its date) or a pull request.
- **How often.** At least once before every minor release, and in an
  out-of-band patch release when a major model change happens (a flagship
  launch, a retirement, a renamed model id). The release checklist includes it.
- **Review.** A pull request that changes `ekte/knowledge/data/*.yaml` needs a
  cited source for every changed value and a second pair of eyes, and
  `ekte kb-import --check` must pass. Set `last_verified` on a provider only
  after you have checked the whole provider file, not just the lines you
  changed.
- **Changelog.** Every change to the bundled data is listed in `CHANGELOG.md`,
  because it can change verdicts.
