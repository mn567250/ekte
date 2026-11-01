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
