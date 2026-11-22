"""The methodology reproduces every published scoring scale and weight table (#263).

``docs/guide/methodology.md`` says every scoring table in it is the detector's
published ``SCALE``. These tests parse the document and compare it with the
code, in both directions: every outcome of every registered detector (chat,
embedding and rerank) must have a row with the same label, status, severity
and effect, every scale row in the document must exist in the code, and the
weight tables must equal ``SURFACE_WEIGHTS``. The seven translations must
carry the same rows (check, status, severity, effect; the labels are
translated).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

import ekte.detectors  # noqa: F401  (registers every detector)
from ekte import scoring
from ekte.detectors.base import REGISTRY
from ekte.detectors.scale import Scale
from ekte.models import Dimension, ScoringOutcome, Severity, Status

DOCS = Path(__file__).resolve().parent.parent / "docs"
DOC = DOCS / "guide" / "methodology.md"

SCALE_HEADER = "| Check | Outcome | Status | Effect |"
WEIGHT_HEADER = "| Dimension | Id | Weight | Role |"
_STATUS = {
    Status.PASS: "Pass",
    Status.WARN: "Warning",
    Status.FAIL: "Fail",
    Status.INCONCLUSIVE: "Inconclusive",
    Status.INFO: "Info",
    Status.NOT_RUN: "Not run",
    Status.ERROR: "Error",
}
# Detectors whose module publishes more than one scale.
_SCALE_ATTR = {"protocol_request": "REQUEST_SCALE", "protocol_response": "RESPONSE_SCALE"}
# The section of the document that lists each surface's weights.
_WEIGHT_SECTIONS = {
    "Overall score, rating and weights": "chat",
    "Embedding surface": "embedding",
    "Rerank surface": "rerank",
}

Row = tuple[str, str, str, str]  # check, label, status cell, effect cell


def _scale_of(det_id: str) -> Scale:
    module = sys.modules[REGISTRY[det_id].__module__]
    scale = getattr(module, _SCALE_ATTR.get(det_id, "SCALE"))
    assert isinstance(scale, Scale), det_id
    return scale


def _num(value: float) -> str:
    return f"{value:g}" if value == int(value) else f"{value:.1f}"


def status_cell(o: ScoringOutcome) -> str:
    cell = _STATUS[o.status]
    return cell if o.severity == Severity.INFO else f"{cell} · {o.severity.value.capitalize()}"


def effect_cell(o: ScoringOutcome, method: str) -> str:
    """The effect as the web UI's scoring scale shows it (``eff`` in report.js)."""
    if method != "deductions":
        return "Not counted" if o.score is None else f"{_num(o.score)} pts"
    parts = []
    if o.deduction:
        parts.append(f"−{_num(o.deduction)} pts")
    elif o.max_deduction:
        parts.append(f"up to −{_num(o.max_deduction)} pts")
    if o.cap is not None:
        parts.append(f"cap {_num(o.cap)}")
    return " · ".join(parts) or "No deduction"


def expected_rows(det_id: str) -> list[Row]:
    scale = _scale_of(det_id)
    return [(o.check, o.label, status_cell(o), effect_cell(o, scale.method)) for o in scale.outcomes]


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse_scale_tables(text: str, header: str = SCALE_HEADER) -> dict[str, list[Row]]:
    """The scale rows of the document per detector: a table belongs to the
    nearest heading above it that names a detector id in backticks."""
    tables: dict[str, list[Row]] = {}
    detector: str | None = None
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        heading = re.match(r"^#{2,4} `([^`]+)`", line)
        if heading:
            detector = heading.group(1)
        elif line.startswith("#"):
            detector = None
        if line.strip() == header:
            assert detector is not None, f"scale table without a detector heading (line {i + 1})"
            rows = tables.setdefault(detector, [])
            check = ""
            i += 2  # header and separator
            while i < len(lines) and lines[i].startswith("|"):
                cells = _cells(lines[i])
                assert len(cells) == 4, f"line {i + 1}: {lines[i]}"
                if cells[0]:
                    m = re.match(r"^`([^`]+)`", cells[0])
                    assert m, f"line {i + 1}: check cell {cells[0]!r}"
                    check = m.group(1)
                rows.append((check, cells[1], cells[2], cells[3]))
                i += 1
            continue
        i += 1
    return tables


def compare(tables: dict[str, list[Row]]) -> list[str]:
    """Every difference between the document's scale tables and the code."""
    problems: list[str] = []
    for det_id in sorted(REGISTRY):
        expected = expected_rows(det_id)
        documented = tables.get(det_id)
        if documented is None:
            problems.append(f"{det_id}: no scoring-scale table in the methodology")
            continue
        for row in expected:
            if row not in documented:
                near = [d for d in documented if d[:2] == row[:2]]
                problems.append(f"{det_id}: row {row} " + (f"documented as {near[0]}" if near else "missing"))
        for row in documented:
            if row not in expected:
                problems.append(f"{det_id}: documented row {row} is not in the code")
    for det_id in sorted(set(tables) - set(REGISTRY)):
        problems.append(f"{det_id}: scale table for an unknown detector")
    return problems


Weights = dict[str, dict[str, tuple[float, bool]]]  # surface -> dimension -> (weight, core)


def parse_weight_tables(text: str) -> Weights:
    """The weight table under each section of ``_WEIGHT_SECTIONS``."""
    out: Weights = {}
    section: str | None = None
    lines = text.splitlines()
    for i, line in enumerate(lines):
        heading = re.match(r"^#{2,3} (.+)$", line)
        if heading:
            section = heading.group(1).strip()
        if line.strip() == WEIGHT_HEADER and section in _WEIGHT_SECTIONS:
            surface = _WEIGHT_SECTIONS[section]
            assert surface not in out, f"two weight tables for {surface}"
            weights: dict[str, tuple[float, bool]] = {}
            for row in lines[i + 2:]:
                if not row.startswith("|"):
                    break
                cells = _cells(row)
                weights[cells[1].strip("`")] = (float(cells[2]), cells[3] == "core")
            out[surface] = weights
    return out


def expected_weights() -> Weights:
    core = scoring._SURFACE_CORE_DIMENSIONS
    return {
        surface: {dim.value: (w, dim in core[surface]) for dim, w in weights.items()}
        for surface, weights in scoring.SURFACE_WEIGHTS.items()
    }


def _doc() -> str:
    return DOC.read_text(encoding="utf-8")


def test_every_published_scale_row_is_documented_and_vice_versa() -> None:
    problems = compare(parse_scale_tables(_doc()))
    assert not problems, "methodology.md disagrees with the scales:\n" + "\n".join(problems)


def test_every_surface_is_covered() -> None:
    surfaces = {cls.surface for cls in REGISTRY.values()}
    assert surfaces == set(scoring.SURFACE_WEIGHTS)
    documented = parse_scale_tables(_doc())
    for surface in surfaces:
        assert any(REGISTRY[d].surface == surface for d in documented), surface


def test_weight_tables_match_surface_weights() -> None:
    assert parse_weight_tables(_doc()) == expected_weights()


@pytest.mark.parametrize(
    ("old", "new"),
    [
        # a label edited in the code but not in the document
        ("| The embeddings endpoint returned vectors. |", "| The embeddings endpoint returned vectors |"),
        # a changed severity
        ("| Fail · High | 0 pts |", "| Fail · Medium | 0 pts |"),
        # a changed effect
        ("| Warning · Low | 60 pts |", "| Warning · Low | 50 pts |"),
        # a row moved to another detector's table
        ("### `rerank.determinism`", "### `rerank.drift`"),
    ],
)
def test_a_document_mismatch_fails(old: str, new: str) -> None:
    text = _doc()
    assert old in text
    assert compare(parse_scale_tables(text.replace(old, new, 1)))


def test_a_missing_row_fails() -> None:
    text = _doc()
    line = next(x for x in text.splitlines() if x.startswith("| `rerank.known_answer` |"))
    assert compare(parse_scale_tables(text.replace(line + "\n", "", 1)))


def test_a_label_changed_in_code_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    scale = _scale_of("embed.connectivity")
    edited = [scale.outcomes[0].model_copy(update={"label": "Edited."}), *scale.outcomes[1:]]
    monkeypatch.setattr(scale, "outcomes", edited)
    assert compare(parse_scale_tables(_doc()))


def test_a_new_outcome_in_code_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    scale = _scale_of("rerank.known_answer")
    extra = scale.outcomes[0].model_copy(update={"outcome": "new", "label": "A new outcome."})
    monkeypatch.setattr(scale, "outcomes", [*scale.outcomes, extra])
    assert compare(parse_scale_tables(_doc()))


@pytest.mark.parametrize(
    "change",
    [
        lambda w: w["rerank"].__setitem__(Dimension.CONNECTIVITY, 11.0),
        lambda w: w["embedding"].pop(Dimension.INTEGRITY),
    ],
)
def test_a_changed_weight_fails(monkeypatch: pytest.MonkeyPatch, change) -> None:
    weights = {s: dict(w) for s, w in scoring.SURFACE_WEIGHTS.items()}
    change(weights)
    monkeypatch.setattr(scoring, "SURFACE_WEIGHTS", weights)
    assert parse_weight_tables(_doc()) != expected_weights()


# --------------------------------------------------------------------------- #
# Translations: the same rows, in each language's UI wording
# --------------------------------------------------------------------------- #

# Per language: the scale-table header, the status and severity words and the
# effect wording (as the existing translated tables write them).
_VOCAB: dict[str, dict] = {
    "de": dict(hdr="| Prüfung | Ergebnis | Status | Wirkung |",
               st=["Bestanden", "Warnung", "Fehlgeschlagen", "Nicht eindeutig", "Info"],
               sev=["Niedrig", "Mittel", "Hoch", "Kritisch"],
               fx=["{n} Pkt.", "Nicht gewertet", "−{n} Pkt.", "bis zu −{n} Pkt.", "Obergrenze {n}", "Kein Abzug"]),
    "es": dict(hdr="| Comprobación | Resultado | Estado | Efecto |",
               st=["Correcto", "Advertencia", "Fallo", "No concluyente", "Info"],
               sev=["Baja", "Media", "Alta", "Crítica"],
               fx=["{n} pts", "No computa", "−{n} pts", "hasta −{n} pts", "tope {n}", "Sin deducción"]),
    "fr": dict(hdr="| Contrôle | Résultat | Statut | Effet |",
               st=["Réussi", "Avertissement", "Échec", "Non concluant", "Info"],
               sev=["Faible", "Moyenne", "Élevée", "Critique"],
               fx=["{n} pts", "Non compté", "−{n} pts", "jusqu'à −{n} pts", "plafond {n}", "Aucune déduction"]),
    "it": dict(hdr="| Controllo | Esito | Stato | Effetto |",
               st=["Superato", "Avviso", "Fallito", "Non conclusivo", "Info"],
               sev=["Bassa", "Media", "Alta", "Critica"],
               fx=["{n} pt", "Non conteggiato", "−{n} pt", "fino a −{n} pt", "tetto {n}", "Nessuna detrazione"]),
    "nb": dict(hdr="| Kontroll | Utfall | Status | Effekt |",
               st=["Bestått", "Advarsel", "Ikke bestått", "Uavklart", "Info"],
               sev=["Lav", "Middels", "Høy", "Kritisk"],
               fx=["{n} poeng", "Telles ikke", "−{n} poeng", "opptil −{n} poeng", "tak {n}", "Ingen fradrag"]),
    "pt": dict(hdr="| Verificação | Resultado | Estado | Efeito |",
               st=["Aprovado", "Aviso", "Falha", "Inconclusivo", "Info"],
               sev=["Baixa", "Média", "Alta", "Crítica"],
               fx=["{n} pts", "Não contabilizado", "−{n} pts", "até −{n} pts", "teto {n}", "Sem dedução"]),
    "zh-CN": dict(hdr="| 检查项 | 结果 | 状态 | 计分 |",
                  st=["通过", "警告", "失败", "不确定", "信息"],
                  sev=["低", "中", "高", "严重"],
                  fx=["{n} 分", "不计分", "−{n} 分", "最多 −{n} 分", "上限 {n}", "不扣分"]),
}
_EN_STATUS = ["Pass", "Warning", "Fail", "Inconclusive", "Info"]
_EN_SEVERITY = ["Low", "Medium", "High", "Critical"]
_EN_EFFECT = ["{n} pts", "Not counted", "−{n} pts", "up to −{n} pts", "cap {n}", "No deduction"]


def _translate_status(cell: str, vocab: dict) -> str:
    status, _, severity = cell.partition(" · ")
    out = vocab["st"][_EN_STATUS.index(status)]
    return out + (" · " + vocab["sev"][_EN_SEVERITY.index(severity)] if severity else "")


def _translate_effect(cell: str, vocab: dict) -> str:
    parts = []
    for part in cell.split(" · "):
        number = re.search(r"\d+(\.\d+)?", part)
        template = part.replace(number.group(0), "{n}") if number else part
        out = vocab["fx"][_EN_EFFECT.index(template)]
        parts.append(out.format(n=number.group(0)) if number else out)
    return " · ".join(parts)


@pytest.mark.parametrize("lang", sorted(_VOCAB))
def test_translations_carry_every_scale_row(lang: str) -> None:
    vocab = _VOCAB[lang]
    text = (DOCS / "i18n" / lang / "guide" / "methodology.md").read_text(encoding="utf-8")
    documented = parse_scale_tables(text, vocab["hdr"])
    problems = []
    for det_id in sorted(REGISTRY):
        expected = [
            (check, _translate_status(status, vocab), _translate_effect(effect, vocab))
            for check, _, status, effect in expected_rows(det_id)
        ]
        got = [(check, status, effect) for check, _, status, effect in documented.get(det_id, [])]
        if got != expected:
            problems.append(f"{det_id}: expected {expected}, documented {got}")
    assert not problems, f"{lang} methodology disagrees with the scales:\n" + "\n".join(problems)
