"""Translations shared by the web UI and the Python side (webhook alerts).

The single source is ``zing/i18n/locales/<code>.json``, one file per language:

* ``meta``     — ``code``, dropdown ``label``, ``html`` lang, date ``locale`` and
  menu ``order``;
* ``strings``  — English string -> translation (``en.json`` is the identity map
  and so the canonical list of translatable strings);
* ``findings`` — finding id -> ``[title, summary template]`` (``zh.json`` holds
  the original Chinese catalog; ``en`` needs none — the backend is English).

The browser gets the same data through ``/locales.js`` (see :func:`locales_script`:
the full bundle, or one language's via ``?lang=`` / the ``zing_lang`` cookie);
this module gives Python code (``zing.notify``) the lookups it needs. Adding a
language means adding one JSON file here — nothing else.

Feature work may also ship its UI strings as fragments,
``locales/fragments/<feature>/<code>.json`` holding just ``{"strings": {…}}``;
they are merged into the language's ``strings`` (so an ``en`` fragment extends
the canonical key list and the completeness tests cover it too).
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

_DIR = Path(__file__).resolve().parent / "locales"
_STATIC_LOCALES_JS = Path(__file__).resolve().parent.parent / "web" / "static" / "locales.js"

DEFAULT = "en"

# Chinese terms the (otherwise English) backend embeds in its sentences.
_GLOSSARY = (("货不对板", "bait-and-switch"), ("中转站", "relay"))
_HEADLINE = re.compile(r"^(?P<sentence>.*?)\s*\(confidence: (?P<conf>low|medium|high)\)$")


@lru_cache(maxsize=1)
def _load() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for path in sorted(_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        out[data["meta"]["code"]] = data
    for path in sorted(_DIR.glob("fragments/*/*.json")):
        code = path.stem
        if code not in out:
            raise ValueError(f"locale fragment for unknown language: {path}")
        frag = json.loads(path.read_text(encoding="utf-8"))
        out[code].setdefault("strings", {}).update(frag.get("strings", {}))
    return out


def languages() -> list[dict[str, Any]]:
    """Language metadata (code, label, html, locale) in menu order."""
    return sorted((d["meta"] for d in _load().values()), key=lambda m: m.get("order", 99))


def codes() -> list[str]:
    return [m["code"] for m in languages()]


def normalize(lang: str | None) -> str:
    """A supported language code; anything unknown or empty becomes English."""
    return _supported(lang) or DEFAULT


def _supported(lang: str | None) -> str | None:
    """``lang`` as a supported code, or ``None``."""
    code = (lang or "").strip().lower()
    return code if code in _load() else None


def ui(lang: str | None, en: str) -> str:
    """English string -> ``lang`` (falls back to the English string)."""
    lang = normalize(lang)
    if lang == DEFAULT:
        return en
    return _load()[lang].get("strings", {}).get(en, en)


def finding_title(lang: str | None, finding_id: str | None, english_title: str) -> str:
    """A finding's title in ``lang``: its catalog title, else the English one."""
    lang = normalize(lang)
    if lang == DEFAULT:
        return backend(lang, english_title)
    cat = _load()[lang].get("findings", {})
    entry = None
    if finding_id:
        entry = cat.get(finding_id)
        if entry is None and finding_id.startswith("model_identity.fp."):
            entry = cat.get("model_identity.fp.*")
    return entry[0] if entry else backend(lang, english_title)


def backend(lang: str | None, text: str | None) -> str:
    """Translate a known backend sentence (exact match or verdict headline).

    Unknown text stays English, minus the Chinese terms it may embed (except
    for ``zh``, where they are kept).
    """
    lang = normalize(lang)
    s = text or ""
    if lang != "zh":
        for zh, en in _GLOSSARY:
            s = s.replace(zh, en)
    if lang == DEFAULT:
        return s
    exact = ui(lang, s)
    if exact != s:
        return exact
    m = _HEADLINE.match(s)
    if m:
        conf = ui(lang, m["conf"].capitalize())
        conf = conf if lang == "zh" else conf.lower()
        suffix = ui(lang, "(confidence: {1})").replace("{1}", conf)
        return ui(lang, m["sentence"]) + ("" if lang == "zh" else " ") + suffix
    return s


def bundle() -> dict[str, Any]:
    """Everything the browser needs: language list + per-language data."""
    data = _load()
    return {
        "languages": languages(),
        "locales": {code: {"strings": d.get("strings", {}), "findings": d.get("findings", {})} for code, d in data.items()},
    }


def lang_bundle(lang: str) -> dict[str, Any]:
    """What a page in ``lang`` needs: the language list, ``lang``'s own data
    (none for ``en``, the key language) and the translatable keys.

    ``keys`` is ``ZING_LOCALES.keys`` precomputed (every English UI string, every
    finding id), so the identity map ``en.json`` need not be sent.
    """
    data = _load()
    d = data[lang]
    locales = {}
    if lang != DEFAULT:
        locales[lang] = {"strings": d.get("strings", {}), "findings": d.get("findings", {})}
    # The other languages' forms of a few backend sentences, so text exported
    # in another language is still recognised (v2/report.js strips them).
    common = {
        code: {en: o["strings"][en] for en in _EVERY_LANGUAGE if en in o.get("strings", {})}
        for code, o in data.items()
        if code not in (DEFAULT, lang)
    }
    return {
        "languages": languages(),
        "lang": lang,
        "locales": locales,
        "common": common,
        "keys": {
            "strings": list(data.get(DEFAULT, {}).get("strings", {})),
            "findings": list(data.get("zh", {}).get("findings", {})),
        },
    }


# Strings every one-language bundle carries for all languages (see lang_bundle).
_EVERY_LANGUAGE = (
    "Overall health score {1}/100.",
    "zing reports black-box evidence of divergence and risk, not proof of fraud.",
)


@lru_cache(maxsize=16)  # one per language + the full bundle
def _script(lang: str | None, _version: tuple[int, int]) -> tuple[str, str]:
    payload = bundle() if lang is None else lang_bundle(lang)
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    body = f"window.ZING_I18N_DATA = {data};\n" + _STATIC_LOCALES_JS.read_text(encoding="utf-8")
    etag = '"' + hashlib.sha256(body.encode("utf-8")).hexdigest()[:20] + '"'
    return body, etag


@lru_cache(maxsize=16)
def _encoded(lang: str | None, _version: tuple[int, int]) -> tuple[bytes, str, bytes]:
    # Compressed once per variant here rather than by the gzip middleware on
    # every response (~56 ms for the full bundle, on the event loop).
    body, etag = _script(lang, _version)
    raw = body.encode("utf-8")
    return raw, etag, gzip.compress(raw, compresslevel=9, mtime=0)


_built_from: list[Any] = [None]  # the _load() result the cached scripts come from


def _variant(lang: str | None) -> tuple[str | None, tuple[int, int]]:
    data = _load()
    if _built_from[0] is not data:
        _script.cache_clear()
        _encoded.cache_clear()
        _built_from[0] = data
    return _supported(lang), (id(data), _STATIC_LOCALES_JS.stat().st_mtime_ns)


def locales_bundle(lang: str | None = None) -> tuple[str, str]:
    """``(script, ETag)`` served at ``/locales.js``, built once per variant.

    ``lang`` (a supported code) gives the one-language bundle (see
    :func:`lang_bundle`); ``None`` or an unknown code the full bundle with
    every language. Rebuilt when the locale data is reloaded
    (``_load.cache_clear()``) or ``static/locales.js`` changes.
    """
    return _script(*_variant(lang))


def locales_encoded(lang: str | None = None) -> tuple[bytes, str, bytes]:
    """:func:`locales_bundle` as served: ``(UTF-8 script, ETag, gzipped script)``,
    built and compressed once per variant."""
    return _encoded(*_variant(lang))


def locales_script(lang: str | None = None) -> str:
    """The JS served at ``/locales.js``: the JSON data, then the lookup logic."""
    return locales_bundle(lang)[0]
