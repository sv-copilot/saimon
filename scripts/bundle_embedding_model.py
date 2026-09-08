#!/usr/bin/env python3
"""Pre-download the local embedding model into a bundled directory.

Downloads exactly the files fastembed requires for the nomic-embed-text
backend (ONNX model + tokenizer/config files) so the Docker runtime never
needs to hit HuggingFace. The bundle is a flat directory consumed via
fastembed's ``specific_model_path``; see research_shared/embedding.py.

Idempotent: huggingface_hub.snapshot_download reuses existing files.
"""

from __future__ import annotations

import argparse
from pathlib import Path

DEFAULT_REPO_ID = "nomic-ai/nomic-embed-text-v1.5"
DEFAULT_OUTPUT = "/opt/saimon/models/nomic-embed-text-v1.5"

# fastembed's TextEmbedding.download_files_from_huggingface() requests these
# allow_patterns plus the model file itself (onnx/model.onnx). Keep them in
# sync with that allowlist so the bundle matches what fastembed would fetch.
ALLOW_PATTERNS = [
    "config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "preprocessor_config.json",
    "onnx/model.onnx",
]


def bundle_model(repo_id: str, output_dir: str | Path) -> Path:
    """Download the model repo into ``output_dir`` (flat layout)."""
    from huggingface_hub import snapshot_download

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=repo_id,
        allow_patterns=ALLOW_PATTERNS,
        local_dir=str(output),
    )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=DEFAULT_REPO_ID)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    output = bundle_model(args.repo, args.output)
    print(f"bundled embedding model to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
