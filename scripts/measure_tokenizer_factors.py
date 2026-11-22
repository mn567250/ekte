#!/usr/bin/env python3
"""Measure the context-window filler's real tokens per heuristic token.

``ekte.utils.tokenize.FILLER_REAL_PER_HEURISTIC`` holds, per tokenizer family
(the ``tokenizer:`` field of ``ekte/knowledge/data/*.yaml``), how many real
tokens the context-window filler (``ekte.detectors.helpers.build_filler``)
counts per heuristic token. ekte never imports a tokenizer at run time, so the
table is data; this script re-measures it offline with the families' published
``tokenizer.json`` files from Hugging Face (issue #261).

For every source below it downloads ``tokenizer.json`` at a pinned revision
(``--latest`` resolves the current one instead), loads it with the
``tokenizers`` library only (no ``transformers``, no repository code, no
``trust_remote_code``), encodes ``build_filler(n, tokenizer=family, nonce=...)``
for every size and nonce without special tokens, and divides the real count by
``heuristic_token_count`` of the same text. A family's factor is the largest
per-source median, rounded UP to two decimals (the probe divides by it, so
rounding up keeps the real count within the rung). A source with
``same_as`` names a gated official repository: its ``tokenizer.json`` must
have the same SHA-256 as the mirror's (read from the Hub's file metadata,
which needs no access), or the source is skipped.

Not run in CI. It needs network access to huggingface.co and two packages that
are not ekte dependencies; install them in a separate virtual environment
together with ekte::

    python -m venv /tmp/tokvenv
    /tmp/tokvenv/bin/pip install -e . tokenizers huggingface_hub
    /tmp/tokvenv/bin/python scripts/measure_tokenizer_factors.py --cache-dir /tmp/tok-cache

Options: ``--family NAME`` (repeatable) limits the run, ``--latest`` measures
the repositories' current revisions, ``--json FILE`` writes every measurement.
Downloaded files are untrusted data: keep ``--cache-dir`` a directory of its
own. See docs/dev/knowledge-base.md ("Tokenizer factors").
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Source:
    repo: str
    revision: str
    # A gated official repository whose tokenizer.json must be byte-identical.
    same_as: str = ""


# Family -> sources (the repositories whose models the knowledge base lists
# under the family, or a faithful ungated mirror). Revisions as measured.
SOURCES: dict[str, list[Source]] = {
    "o200k_base": [Source("Xenova/gpt-4o", "7956d98f2a83b2751a98ea7136fdf7fe6cf54e69")],
    "o200k_harmony": [
        Source("openai/gpt-oss-20b", "6cee5e81ee83917806bbde320786a8fb61efebee"),
        Source("openai/gpt-oss-120b", "b5c939de8f754692c1647ca79fbf85e8c1e70f8a"),
    ],
    "cl100k_base": [
        Source("Xenova/text-embedding-ada-002", "f20698771af1ad4cacd2a6219bd13c0ea5d9b3de"),
        Source("Xenova/gpt-4", "1d9f1f1b1fae88c0e4df1dab0a397f8de6229075"),
    ],
    "qwen": [
        Source("Qwen/Qwen3-8B", "b968826d9c46dd6066d109eabc6255188de91218"),
        Source("Qwen/Qwen3-235B-A22B-Instruct-2507", "ac9c66cc9b46af7306746a9250f23d47083d689e"),
        Source("Qwen/Qwen3.5-397B-A17B", "8472618112abcbd45acbcdc58436aff4233c23f7"),
        Source("Qwen/Qwen3.6-35B-A3B", "345d467b117d1fd5eda9b879a5988de9ae5f47a7"),
        Source("Qwen/Qwen3.8-27B", "37561816e66b5b9153b1b64c10968c18c1e6f4a0"),
        Source("Qwen/Qwen3.8-Flash-Next", "812d96e10a0dd82b69d749e68693698cf6c36daa"),
    ],
    "deepseek-bpe": [
        Source("deepseek-ai/DeepSeek-V4-Pro", "b5968e9190ef611bbf34a7229255be88a0e937c1"),
        Source("deepseek-ai/DeepSeek-V4-Flash", "60d8d70770c6776ff598c94bb586a859a38244f1"),
        Source("deepseek-ai/DeepSeek-V3.2", "a7e62ac04ecb2c0a54d736dc46601c5606cf10a6"),
        Source("deepseek-ai/DeepSeek-V3.1", "c0781d039fb7a1ba2abc4add0bdc293e92d2b8db"),
    ],
    "glm": [
        Source("zai-org/GLM-5", "c183ef8c61faee82855eca1ed9bb3a9a7ce3b0b2"),
        Source("zai-org/GLM-4.7", "602d01efcdd332c5238ca4bcede555defbe83eb7"),
        Source("zai-org/GLM-4.6", "be72194883d968d7923a07e2f61681ea9a2826d1"),
        Source("zai-org/GLM-4.5", "cbb2c7cfb52fa128a9660cb1a7a78e017899e115"),
    ],
    "gemma": [
        Source("google/gemma-4-31b-it", "842da3794eaa0b77d5f08bae87a17459d91ff475"),
        Source("google/gemma-4-E4B-it", "4ecc2ba63bcac23ba4a767fc87025b1450f84c9c"),
        Source("unsloth/gemma-3-27b-it", "7a5a3053dbd5d1d58e48159e87b9df2fc545a49a", same_as="google/gemma-3-27b-it"),
    ],
    "nemotron-3": [
        Source("nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16", "2dc98e2afe4face0e4ce40972a915c45368bd34a"),
        Source("nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16", "bf77c3174f68ad409e1c2aa60daeb46e32d1c606"),
    ],
    "llama-3.3": [
        Source(
            "nvidia/Llama-3_3-Nemotron-Super-49B-v1_5", "420ba7d28211abf116b8b103ab700d92619daf98",
            same_as="meta-llama/Llama-3.3-70B-Instruct",
        ),
    ],
    "cohere": [
        Source(
            "mlx-community/c4ai-command-r7b-12-2024-bf16", "f111eceb4c3dba69b2a4f5dc9f57f293fb416b8a",
            same_as="CohereLabs/c4ai-command-r7b-12-2024",
        ),
    ],
}

SIZES = (1_000, 8_000, 32_000, 128_000)
# Fixed nonces so a re-run measures the same texts; "" is the pre-nonce filler.
NONCES = ("", "0123456789abcdef", "9f3c2a71e04b5d68", "d41d8cd98f00b204", "ekte-261-factor")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _hub_sha256(api: Any, repo: str, revision: str | None = None) -> tuple[str, str | None]:
    """The revision and the LFS SHA-256 of ``repo``'s tokenizer.json (metadata
    only: works for a gated repository without access)."""
    info = api.model_info(repo, revision=revision, files_metadata=True)
    for sibling in info.siblings or []:
        if sibling.rfilename == "tokenizer.json":
            return info.sha, (sibling.lfs.sha256 if sibling.lfs else None)
    return info.sha, None


def measure_source(family: str, source: Source, *, cache_dir: Path, latest: bool) -> dict[str, Any]:
    from huggingface_hub import HfApi, hf_hub_download
    from tokenizers import Tokenizer

    from ekte.detectors.helpers import build_filler
    from ekte.utils.tokenize import heuristic_token_count

    api = HfApi()
    revision, hub_sha = _hub_sha256(api, source.repo, None if latest else source.revision)
    row: dict[str, Any] = {"family": family, "repo": source.repo, "revision": revision}
    path = Path(hf_hub_download(source.repo, "tokenizer.json", revision=revision, cache_dir=str(cache_dir)))
    row["sha256"] = _sha256(path)
    if hub_sha and hub_sha != row["sha256"]:
        row["skipped"] = f"download sha256 {row['sha256']} != hub metadata {hub_sha}"
        return row
    if source.same_as:
        _, official = _hub_sha256(api, source.same_as)
        row["same_as"] = source.same_as
        if official != row["sha256"]:
            row["skipped"] = f"not identical to {source.same_as} ({official})"
            return row
    tokenizer = Tokenizer.from_file(str(path))
    samples = []
    for size in SIZES:
        for nonce in NONCES:
            text = build_filler(size, tokenizer=family, nonce=nonce)
            heuristic = heuristic_token_count(text)
            real = len(tokenizer.encode(text, add_special_tokens=False).ids)
            samples.append({"size": size, "nonce": nonce, "heuristic": heuristic, "real": real, "ratio": real / heuristic})
    ratios = [s["ratio"] for s in samples]
    row.update(
        samples=samples,
        median=statistics.median(ratios),
        min=min(ratios),
        max=max(ratios),
    )
    return row


def factor(median: float) -> float:
    """A median ratio rounded up to two decimals."""
    return math.ceil(median * 100 - 1e-9) / 100


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--cache-dir", type=Path, required=True, help="download directory (its own, empty)")
    parser.add_argument("--family", action="append", default=[], help="measure only this family (repeatable)")
    parser.add_argument("--latest", action="store_true", help="measure the current revisions, not the pinned ones")
    parser.add_argument("--json", type=Path, help="write every measurement to this file")
    args = parser.parse_args(argv)

    unknown = set(args.family) - set(SOURCES)
    if unknown:
        parser.error(f"unknown family: {', '.join(sorted(unknown))} (known: {', '.join(SOURCES)})")
    families = args.family or list(SOURCES)
    rows = []
    for family in families:
        for source in SOURCES[family]:
            row = measure_source(family, source, cache_dir=args.cache_dir, latest=args.latest)
            rows.append(row)
            if "skipped" in row:
                print(f"{family:14s} {source.repo:48s} SKIPPED: {row['skipped']}", file=sys.stderr)
            else:
                print(
                    f"{family:14s} {source.repo:48s} {row['revision'][:12]}  "
                    f"median {row['median']:.4f}  spread {row['min']:.4f}-{row['max']:.4f}"
                )
    print("\nFILLER_REAL_PER_HEURISTIC candidates (largest source median, rounded up):")
    for family in families:
        measured = [r for r in rows if r["family"] == family and "median" in r]
        if measured:
            low = min(r["min"] for r in measured)
            high = max(r["max"] for r in measured)
            best = max(r["median"] for r in measured)
            print(f'    "{family}": {factor(best):.2f},  # median {best:.4f}, spread {low:.4f}-{high:.4f}')
    if args.json:
        args.json.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
