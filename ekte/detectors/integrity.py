"""Response-integrity / tampering detector.

A malicious proxy can rewrite content in flight — typosquatting an install URL or
package name, swapping a wallet address or a repository — while leaving
everything else intact. Such rewriting in the wild is targeted: it looks for
well-known install URLs, popular package names and wallet addresses. ekte sends
known-answer canaries ("output exactly this line") carrying exactly such values
— two synthetic ones, a well-known installer URL, a popular pinned package, a
``git clone`` line and a valid-format cryptocurrency address derived from the
audited endpoint and model (no fixed value a relay could allow-list) — and checks whether the structure comes back with the
value SUBSTITUTED. One canary is sent streamed and, when the profile claims tool
calling, one as a tool-call argument, so the other channels a proxy can rewrite
are covered too.

It is deliberately precise to avoid false positives: an exact echo is PASS, a
non-echo (the model didn't comply / paraphrased) is INCONCLUSIVE, and only a
*structure-preserved value substitution* is treated as tampering. A substitution
is confirmed before it counts as more than MEDIUM:

* in ``compare`` mode, a substitution the trusted baseline does NOT make (it
  returns the canary intact) is CRITICAL;
* without a usable baseline (none, or one that errors or returns nothing
  usable), the substituted canary is sent once more: substituted again → HIGH;
  intact on the repeat (or no usable repeat) → it stays MEDIUM.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ekte import prompts
from ekte.context import AuditContext
from ekte.detectors import advice
from ekte.detectors.base import Detector, register
from ekte.detectors.helpers import contains_ci
from ekte.detectors.scale import Scale, outcome
from ekte.models import DetectorResult, Dimension, RequestSpec, Severity, Status

# Canaries in flight at once: enough to overlap latency, few enough not to trip
# a relay's rate limit (as in protocol_attrs).
_CONCURRENCY = 3
# The detector never sends more than this many requests to the target: six
# text canaries, the tool-argument canary and one repeat.
MAX_TARGET_CALLS = 8

# --------------------------------------------------------------------------- #
# bech32 (BIP-173 / BIP-350): a valid-format Bitcoin address made at run time
# --------------------------------------------------------------------------- #
_BECH32 = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_BECH32_CONST = 1
_BECH32M_CONST = 0x2BC830A3


def _polymod(values: list[int]) -> int:
    gen = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    chk = 1
    for v in values:
        top = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ v
        for i in range(5):
            chk ^= gen[i] if (top >> i) & 1 else 0
    return chk


def _hrp_expand(hrp: str) -> list[int]:
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]


def _to_5bit(data: bytes) -> list[int]:
    acc, bits, out = 0, 0, []
    for b in data:
        acc = (acc << 8) | b
        bits += 8
        while bits >= 5:
            bits -= 5
            out.append((acc >> bits) & 31)
    if bits:
        out.append((acc << (5 - bits)) & 31)
    return out


def bech32_address(program: bytes, hrp: str = "bc") -> str:
    """A segwit v0 (P2WPKH-shaped) address for a 20-byte ``program``."""
    data = [0, *_to_5bit(program)]
    poly = _polymod([*_hrp_expand(hrp), *data, 0, 0, 0, 0, 0, 0]) ^ _BECH32_CONST
    checksum = [(poly >> 5 * (5 - i)) & 31 for i in range(6)]
    return hrp + "1" + "".join(_BECH32[d] for d in data + checksum)


def is_bech32_address(value: str, hrp: str = "bc") -> bool:
    """Whether ``value`` is a well-formed bech32/bech32m address for ``hrp``.

    A model that miscopies one character of a random address breaks the
    checksum; a proxy that swaps in its own wallet keeps it valid. Only the
    latter is a substitution.
    """
    if value != value.lower() and value != value.upper():
        return False
    v = value.lower()
    if not v.startswith(hrp + "1") or not 14 <= len(v) <= 90:
        return False
    data_part = v[len(hrp) + 1:]
    if any(c not in _BECH32 for c in data_part):
        return False
    data = [_BECH32.index(c) for c in data_part]
    return _polymod([*_hrp_expand(hrp), *data]) in (_BECH32_CONST, _BECH32M_CONST)


# --------------------------------------------------------------------------- #
# canaries
# --------------------------------------------------------------------------- #
@dataclass
class _Canary:
    id: str
    prompt: str
    expected: str                 # exact substring that must survive intact
    pattern: re.Pattern           # matches the structure (group(0)) and value(s)
    correct: str                  # the canonical value the structure should carry
    channel: str = "text"         # "text", "stream" or "tool"
    # A changed value only counts as a substitution if it passes this check
    # (e.g. a valid address checksum rather than a miscopied character).
    plausible: Callable[[str], bool] | None = None
    tool: dict[str, Any] | None = field(default=None, repr=False)

    def substitution(self, text: str) -> str | None:
        """Return a description if the structure is present but the value changed."""
        m = self.pattern.search(text or "")
        if not m:
            return None
        found = m.group("val")
        if found.casefold() == self.correct.casefold():
            return None
        if self.plausible is not None and not self.plausible(found):
            return None
        return f"{self.id}: expected {self.correct!r}, got {found!r}"


_TOOL_URL = "https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh"


def wallet_address(ctx: AuditContext) -> str:
    """The wallet canary's address: a valid bech32 address no list can know in
    advance, derived from the run's nonce, so every run sends another one.

    Not a random draw here: a replay of a recorded run (ekte.replay) reuses the
    recorded nonce and must send byte-identical requests. Without a nonce (the
    replay of a run from before it existed) the address is derived from the
    audited endpoint and model, as those runs did.
    """
    seed = getattr(ctx, "run_nonce", "")
    if not seed:
        target = getattr(ctx, "target", None)
        seed = "|".join(
            str(getattr(target, k, "") or "") for k in ("base_url", "model", "claimed_model")
        )
    return bech32_address(hashlib.sha256(f"ekte-integrity-wallet|{seed}".encode()).digest()[:20])


def _canaries(*, tools: bool, address: str) -> list[_Canary]:
    """The canaries of one run."""
    canaries = [
        _Canary(
            id="install_url",
            prompt=prompts.text("integrity.install_url"),
            expected="https://downloads.ekte.test/safe/setup.sh",
            pattern=re.compile(r"EKTE_URL=https?://(?P<val>[^/\s\"']+)", re.I),
            correct="downloads.ekte.test",
        ),
        _Canary(
            id="package_pin",
            prompt=prompts.text("integrity.package_pin"),
            expected="ekte==0.1.0",
            pattern=re.compile(r"pip install (?P<val>[A-Za-z0-9._-]+==[0-9][0-9A-Za-z.\-]*)"),
            correct="ekte==0.1.0",
        ),
        _Canary(
            id="installer_url",
            prompt=prompts.text("integrity.installer_url"),
            expected="curl -fsSL https://sh.rustup.rs | sh",
            pattern=re.compile(r"curl\s+-\w+\s+https?://(?P<val>[^/\s\"'|`]+)", re.I),
            correct="sh.rustup.rs",
        ),
        _Canary(
            id="popular_package",
            prompt=prompts.text("integrity.popular_package"),
            expected="pip install requests==2.32.3",
            pattern=re.compile(r"pip install (?P<val>[A-Za-z0-9._-]+==[0-9][0-9A-Za-z.\-]*)"),
            correct="requests==2.32.3",
        ),
        _Canary(
            id="wallet_address",
            prompt=prompts.text("integrity.wallet_address", address=address),
            expected=address,
            pattern=re.compile(r"PAY_TO=(?P<val>[A-Za-z0-9]+)", re.I),
            correct=address,
            plausible=is_bech32_address,
        ),
        _Canary(
            id="git_clone",
            prompt=prompts.text("integrity.git_clone"),
            expected="git clone https://github.com/pallets/flask.git",
            # the value is host/org/repo; a dropped ".git" or a trailing "/" is not a change
            pattern=re.compile(
                r"git clone https?://(?P<val>[^\s\"'`]+?)(?:\.git)?/?(?=[\s\"'`]|$)", re.I
            ),
            correct="github.com/pallets/flask",
            # sent streamed: a proxy may rewrite the SSE deltas it forwards
            channel="stream",
        ),
    ]
    if tools:
        canaries.append(
            _Canary(
                id="tool_argument",
                prompt=prompts.text("integrity.tool_argument"),
                expected=_TOOL_URL,
                pattern=re.compile(r"^\s*https?://(?P<val>[^\s\"'?#]+?)/?\s*$", re.I),
                correct=_TOOL_URL.split("://", 1)[1],
                channel="tool",
                tool=prompts.get("integrity.tool_argument.download_tool"),
            )
        )
    return canaries


def _tool_url(tool_calls: list[dict[str, Any]], name: str) -> str | None:
    """The ``url`` argument of the first call to ``name``, if any."""
    for call in tool_calls:
        fn = call.get("function") if isinstance(call, dict) else None
        if not isinstance(fn, dict) or fn.get("name") != name:
            continue
        args = fn.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                return None
        url = args.get("url") if isinstance(args, dict) else None
        return url if isinstance(url, str) and url.strip() else None
    return None


# The detector score is its one verdict's points (the published scale).
SCALE = Scale(
    outcome("integrity.verdict", "intact", 100.0, Status.PASS,
            label="Known-answer canaries came back intact."),
    outcome("integrity.verdict", "tampering", 45.0, Status.FAIL, Severity.MEDIUM,
            label="A canary value was substituted once, confirmed neither by a baseline nor by a repeat."),
    outcome("integrity.verdict", "tampering_repeated", 20.0, Status.FAIL, Severity.HIGH,
            label="A canary value was substituted again when the same canary was sent a second time."),
    outcome("integrity.verdict", "tampering_corroborated", 10.0, Status.FAIL, Severity.CRITICAL,
            label="A canary value was substituted while the trusted baseline kept it intact."),
    outcome("integrity.verdict", "inconclusive", None, Status.INCONCLUSIVE,
            label="No canary was echoed verbatim, so tampering could not be assessed."),
    titles={"integrity.verdict": "Response integrity"},
)


@register
class IntegrityDetector(Detector):
    id = "integrity"
    name = "Response integrity / tampering"
    dimension = Dimension.INTEGRITY
    min_suite = "deep"
    cost_hint = MAX_TARGET_CALLS

    async def run(self, ctx: AuditContext) -> DetectorResult:
        result = self.new_result(scoring=SCALE.scoring())
        model = ctx.profile.model if ctx.profile else None
        canaries = _canaries(tools=bool(model and model.supports_tools),
                             address=wallet_address(ctx))
        sem = asyncio.Semaphore(_CONCURRENCY)
        calls = 0

        async def ask(canary: _Canary, *, baseline: bool = False) -> str | None:
            nonlocal calls
            if not baseline:
                calls += 1
            async with sem:
                return await self._ask_canary(ctx, canary, baseline=baseline)

        answers = await asyncio.gather(*(ask(c) for c in canaries))

        # Substituted canaries, in canary order.
        substituted: list[tuple[_Canary, str]] = []
        verbatim = 0
        noncompliant = 0
        for canary, text in zip(canaries, answers, strict=True):
            if text is None:
                noncompliant += 1
            elif contains_ci(text, canary.expected):
                verbatim += 1
            elif sub := canary.substitution(text):
                substituted.append((canary, sub))
            else:
                noncompliant += 1

        # Per substitution: did the trusted baseline return that canary intact?
        # Only a baseline that actually answered — verbatim — corroborates; one
        # that errored or returned nothing usable leaves the substitution
        # uncorroborated.
        substitutions: list[str] = []
        baseline_intact: list[bool] = []
        repeat_canaries: list[_Canary] = []
        if substituted and ctx.has_baseline:
            bases = await asyncio.gather(*(ask(c, baseline=True) for c, _ in substituted))
        else:
            bases = [None] * len(substituted)
        result.baseline_compared = any(base is not None for base in bases)
        for (canary, sub), base in zip(substituted, bases, strict=True):
            if base is not None and not contains_ci(base, canary.expected):
                # Baseline also failed to echo it — likely model behavior, not tampering.
                noncompliant += 1
                continue
            substitutions.append(sub)
            baseline_intact.append(base is not None)
            repeat_canaries.append(canary)

        result.evidence.update(
            {"substitutions": substitutions, "verbatim": verbatim, "noncompliant": noncompliant,
             "channels": sorted({c.channel for c in canaries})}
        )

        if substitutions:
            confirmed = [sub for sub, ok in zip(substitutions, baseline_intact, strict=True) if ok]
            corroborated = bool(confirmed)
            # Compare mode ran, but the baseline errored / answered nothing usable
            # (empty, cut off) for every substituted canary — it confirmed nothing.
            baseline_unavailable = ctx.has_baseline and not corroborated
            evidence: dict[str, Any] = {
                "substitutions": substitutions,
                "baseline_corroborated": corroborated,
                "baseline_unavailable": baseline_unavailable,
                # the substitutions the baseline returned intact
                "corroborated_substitutions": confirmed,
                "repeat_substituted": False,
            }
            repeated = False
            if not corroborated:
                # No usable baseline: confirm by sending the first substituted
                # canary once more, on the same channel.
                canary = repeat_canaries[0]
                again = await ask(canary)
                repeat_sub = canary.substitution(again) if again is not None else None
                repeat_intact = again is not None and contains_ci(again, canary.expected)
                repeated = repeat_sub is not None and not repeat_intact
                evidence.update(
                    {
                        "repeated_canary": canary.id,
                        "repeat_intact": repeat_intact,
                        "repeat_substituted": repeated,
                        "repeat_substitution": repeat_sub if repeated else None,
                    }
                )
            if corroborated:
                key = "tampering_corroborated"
                unconfirmed = len(substitutions) - len(confirmed)
                tail = (
                    " — and the trusted baseline returned it intact, strong evidence "
                    "of in-flight tampering."
                    + (
                        f" ({unconfirmed} other substitution(s) could not be checked: "
                        "the baseline returned no usable answer for them.)"
                        if unconfirmed
                        else ""
                    )
                )
            elif repeated:
                key = "tampering_repeated"
                tail = (
                    " — and it was substituted again when the same canary was sent a "
                    "second time, so the rewrite is systematic, not a one-off."
                    + (
                        " The trusted baseline returned no usable answer to corroborate it."
                        if baseline_unavailable
                        else " Run `ekte compare` against a trusted baseline to corroborate it."
                    )
                )
            else:
                key = "tampering"
                again_note = (
                    " It came back intact when the same canary was sent a second time."
                    if evidence["repeat_intact"]
                    else " Sending the same canary a second time gave no usable answer."
                )
                if baseline_unavailable:
                    tail = (
                        ". The trusted baseline returned no usable answer (error, empty or "
                        "cut off) for the substituted canary value(s), so the substitution is "
                        "not corroborated; re-run `ekte compare` once the baseline answers."
                        + again_note
                    )
                else:
                    tail = (
                        "." + again_note + " Treat as a strong signal; run `ekte compare` "
                        "against a trusted baseline to confirm."
                    )
            result.findings.append(
                SCALE.finding(
                    "integrity.verdict",
                    key,
                    id="integrity.tampering",
                    title="Relay-controlled value substitution detected",
                    summary=(
                        "A known-answer canary came back with its value substituted while "
                        "its structure was preserved" + tail
                    ),
                    evidence=evidence,
                    recommendation="A proxy rewriting URLs/package names is a supply-chain risk — stop using it.",
                )
            )
            result.status = Status.FAIL
            result.score = Scale.mean(result.findings)
        elif verbatim:
            result.findings.append(
                SCALE.finding(
                    "integrity.verdict",
                    "intact",
                    id="integrity.intact",
                    title="Known-answer canaries returned intact",
                    summary=f"{verbatim} canary value(s) echoed verbatim; no substitution observed.",
                    evidence={"verbatim": verbatim, "noncompliant": noncompliant},
                )
            )
            result.status = Status.PASS
            result.score = Scale.mean(result.findings)
        else:
            result.findings.append(
                SCALE.finding(
                    "integrity.verdict",
                    "inconclusive",
                    id="integrity.inconclusive",
                    title="Integrity canaries inconclusive",
                    summary="The model did not echo any canary verbatim, so tampering could not be assessed.",
                    recommendation=advice.NO_CANARY_ECHO,
                    evidence={"noncompliant": noncompliant},
                )
            )
            result.status = Status.INCONCLUSIVE
            result.score = None
        result.evidence["calls"] = calls
        return result

    async def _ask_canary(
        self, ctx: AuditContext, canary: _Canary, *, baseline: bool = False
    ) -> str | None:
        """The canary's answer on its channel: text, or the tool call's URL argument."""
        if canary.channel != "tool":
            return await self._ask(ctx, canary.prompt, baseline=baseline,
                                   stream=canary.channel == "stream")
        client = ctx.baseline_client if baseline else ctx.client
        if client is None or canary.tool is None:
            return None
        out = await client.complete(
            RequestSpec(
                messages=[{"role": "user", "content": canary.prompt}],
                tools=[canary.tool],
                tool_choice="auto",
                temperature=0.0,
                max_tokens=128,
            )
        )
        if not out.ok:
            return None
        return _tool_url(out.tool_calls, canary.tool["function"]["name"])

    async def _ask(
        self, ctx: AuditContext, prompt: str, *, baseline: bool = False, stream: bool = False
    ) -> str | None:
        client = ctx.baseline_client if baseline else ctx.client
        if client is None:
            return None
        outcome = await client.complete(
            RequestSpec(messages=[{"role": "user", "content": prompt}], temperature=0.0,
                        max_tokens=80, stream=stream)
        )
        # An answer cut off at the output limit (e.g. `==0` for `==0.1.0` after a
        # reasoning model thought through the budget) is not a substitution.
        if outcome.ok and outcome.has_content() and outcome.finish_reason != "length":
            return outcome.content
        return None
