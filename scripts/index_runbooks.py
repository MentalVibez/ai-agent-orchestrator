#!/usr/bin/env python3
"""Bulk-index IT runbooks from config/runbooks/ into ChromaDB.

Usage:
  python scripts/index_runbooks.py [--collection runbooks] [--runbooks-dir config/runbooks]

This script reads all .md files from the runbooks directory and indexes them
into ChromaDB so the DEX platform can surface relevant resolution steps when
alerts fire (via GET /api/v1/dex/endpoints/{hostname}/runbooks).

Requires chromadb to be installed: pip install chromadb
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure the project root is on the path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description="Index IT runbooks into ChromaDB for DEX RAG")
    parser.add_argument("--collection", default="runbooks", help="ChromaDB collection name")
    parser.add_argument(
        "--runbooks-dir",
        default=str(PROJECT_ROOT / "config" / "runbooks"),
        help="Directory containing .md runbook files",
    )
    parser.add_argument(
        "--chroma-dir",
        default="",
        help="ChromaDB persistence directory (empty = use CHROMA_PERSIST_DIRECTORY env var)",
    )
    args = parser.parse_args()

    runbooks_path = Path(args.runbooks_dir)
    if not runbooks_path.exists():
        print(f"ERROR: Runbooks directory not found: {runbooks_path}")
        sys.exit(1)

    md_files = list(runbooks_path.glob("*.md"))
    if not md_files:
        print(f"No .md files found in {runbooks_path}")
        sys.exit(0)

    # Set up ChromaDB
    try:
        import chromadb
    except ImportError:
        print("ERROR: chromadb is not installed. Run: pip install chromadb")
        sys.exit(1)

    from app.core.config import settings

    chroma_dir = args.chroma_dir or settings.chroma_persist_directory
    if chroma_dir:
        client = chromadb.PersistentClient(path=chroma_dir)
        print(f"Using persistent ChromaDB at: {chroma_dir}")
    else:
        client = chromadb.Client()
        print("Using in-memory ChromaDB (data will not persist across restarts)")

    collection = client.get_or_create_collection(args.collection)

    indexed = 0
    for md_file in sorted(md_files):
        doc_id = md_file.stem  # filename without extension
        content = md_file.read_text(encoding="utf-8")

        # Extract title from first H1 heading
        title = doc_id
        for line in content.splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break

        # Upsert (add or update)
        collection.upsert(
            ids=[doc_id],
            documents=[content],
            metadatas=[{"title": title, "source": str(md_file.name), "collection": args.collection}],
        )
        print(f"  Indexed: {doc_id} — {title}")
        indexed += 1

    print(f"\nDone. {indexed} runbook(s) indexed into collection '{args.collection}'.")
    if not chroma_dir:
        print(
            "NOTE: Set CHROMA_PERSIST_DIRECTORY in your .env file to persist runbooks across restarts."
        )


if __name__ == "__main__":
    main()
