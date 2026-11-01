# Translations

The UI and the webhook alerts share one set of translations in
`ekte/i18n/locales/<code>.json`:

- `meta` — code, the language's own name for the dropdown, `html` lang, date
  locale and menu order;
- `strings` — English text → translation (`en.json` is the identity map and the
  canonical list of translatable strings);
- `findings` — finding id → `[title, summary template]` (`zh.json` holds the
  original Chinese catalog).

Features may ship their strings as fragments,
`ekte/i18n/locales/fragments/<feature>/<code>.json` holding
`{"strings": {…}}`, merged into the language at load time.
`/locales.js` sends only the chosen language (`?lang=<code>` or the `ekte_lang`
cookie `lang.js` sets; every language without either), built and gzipped once
per variant and revalidated by `ETag`; switching loads the new language on
demand.

- **UI text:** write the Chinese in the HTML and the English in `data-en`
  (or use `T(zh, en)`), then add the English key to `en.json` or a fragment and
  its translation to every other language.
- **New language:** add `ekte/i18n/locales/<code>.json` (copy `de.json`) and a
  file per fragment; the dropdown, the pages, the alerts and `--alert-lang` pick
  it up.
- `tests/test_web_locales.py` fails until every UI string and finding is
  translated with its placeholders and markup intact.

**Wording.** A term has one translation per language. Reuse the wording the UI
already uses (page names, dimension names, risk labels, button labels) in new
strings and in the documentation.

## Documentation

User-facing documentation exists in eight languages — English, Chinese
(`zh-CN`), French, Spanish, Portuguese, Italian, German and Norwegian (Bokmål,
`nb`); developer and reference documentation is English only:

| Files | Audience | Languages |
|---|---|---|
| `README.md` | Users: what ekte is, install, first steps; also the PyPI description | all |
| `docs/guide/*.md` | Users: one page per topic, the methodology included | all |
| `docs/reference/*.md` | Command line, schemas, stability policy (contracts) | English |
| `docs/dev/*.md` | Contributors: architecture, UI, processes | English |
| `docs/CONTRIBUTING.md`, `docs/SECURITY.md`, `docs/CODE_OF_CONDUCT.md` | Community files GitHub links to | English |

Translations live in `docs/i18n/<lang>/` and mirror the English files:
`README.md` → `docs/i18n/<lang>/README.md`, `docs/guide/<page>.md` →
`docs/i18n/<lang>/guide/<page>.md`. Every translated page starts with the same
language bar; links from a translation point to the other translations of its
language, and to the English file where there is no translation.

The English files are the reference. When you change one, change every
translation in the same pull request, and use the UI's own wording in each
language (look the term up in `ekte/i18n/locales/`). The methodology quotes the
scoring scales with the wording the UI shows under **Scoring scale**. A new
user guide page needs a translation in every language and a row in the
README's documentation table.

The `README.md` is also the package description on PyPI. Write it in plain
Markdown: no table of contents or in-page anchors and no GitHub-only markup
(alerts, Mermaid, HTML layout). Relative links are fine: the build
(`scripts/hatch_readme.py`) rewrites them to absolute GitHub links for the
released version, and the `Distribution contents` workflow fails when one is
left.

### The translation check

CI runs `python scripts/check_translations.py` (also covered by
`pytest tests/test_docs_translations.py`; `--lang de` checks one language). It
does not judge wording; it fails when a translation differs from the English
source in heading levels and count, code blocks and commands, link targets,
CLI flags / endpoints / field names in inline code, `{placeholders}` or version
numbers, or when a relative link or an anchor does not resolve.

If you cannot write a translation, update the English text, copy the changed
structure (headings, code blocks, links) into the translation, and mark the
file as pending by adding this line anywhere in it:

```markdown
<!-- translation-pending: short reason, e.g. "new section needs a translator" -->
```

A pending translation is skipped by the structure comparison, but its links
must still resolve. Say in the pull request which translations are pending, and
remove the marker once the text is translated.

To add a language, create `docs/i18n/<lang>/` with every translated file and
add its code to `LANGUAGES` in `scripts/check_translations.py`; the check then
covers it.
