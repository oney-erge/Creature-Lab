"""Stable content hashing for spec provenance.

Used to stamp creature/task hashes into an EpisodeTrace so a saved run is
self-describing. The hash is canonical (sorted keys), so it is stable across
re-serialization and independent of field insertion order.
"""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel


def spec_hash(model: BaseModel, exclude: set[str] | None = None) -> str:
    """Return a deterministic ``sha256:<hex>`` digest of a Pydantic model (minus ``exclude``)."""
    data = model.model_dump(mode="json", exclude=exclude)
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
