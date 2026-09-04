"""On-disk store for manual annotations (comments and labels) attached to
records of a JSONL result file.

The web viewer's commentor panel reads and writes through this module, and the
qualitative analysis pipeline (``throwgen.utils.qualitative_analysis``) reads
the same files, so annotations made in the browser feed the paper numbers
directly.

Layout::

    analysis/annotations/{commentor_id}/{slug}.jsonl

Annotations live next to the other manual analysis under ``analysis/`` rather
than under ``_work/``, because they are hand-made data that no pipeline can
regenerate: losing them would cost another full round of manual inspection.

``slug`` is the result file's path relative to the project directory with
``/`` replaced by ``__`` and the ``.jsonl`` suffix dropped. Each line is one
annotated record::

    {"record_index": 12, "data_id": "ne2e-118", "entries": [{"values": {...}}],
     "created_at": "...", "updated_at": "..."}
"""

import datetime
import json
from pathlib import Path
from typing import Any

import seutil as su

from etestgen.macros import Macros as ExlongMacros
from throwgen.macros import Macros as ThrowgenMacros

# Commentor used for the qualitative false positive analysis (see the
# "Qualitative Analysis" section of the paper): the store the viewer's
# annotation panel writes to unless THROWGEN_VIEWER_QUAL_COMMENTOR names another
# one, and the store the analysis reads.
#
# This is the reconciled set -- the first inspector's labels, settled against
# the other two annotators where they read a record differently. The stores it
# is settled against are named in
# ``throwgen.utils.qualitative_analysis.AGREEMENT_STORES``.
QUAL_COMMENTOR_ID = "qual-false-positive-a-recon"

# The false positive categories offered by the viewer's annotation form, as
# defined in analysis/annotations/README.md. Keep the spelling in
# sync with the macros in papers/*/tables/qualitative-numbers.tex, which are
# keyed by these strings.
#
# `too-strict` and `too-lenient` require strict containment of one throwing set in
# the other and are mutually exclusive; `wrong-exception-handling` is the
# catch-all for everything else -- crossing sets, a side effect on the wrong side
# of the throw, a differing return value. `code-destroyed` is decided against the
# model's input rather than against gold, so it can accompany any of them. That
# makes `code-destroyed` plus one behavioural label the only routine pair.
FALSE_POSITIVE_CATEGORIES = [
    "code-destroyed",
    "too-strict",
    "too-lenient",
    "wrong-exception-handling",
]

# What an earlier category becomes under the four above, where the answer is
# forced. Measured on the 114 ERCs that both the six-category round and the
# four-category round call non-equivalent, so both vocabularies describe the
# same record and the same rater assigned each -- see
# analysis/annotations/reconciliation/README.md.
#
# A mapping is listed only when the new label fired on *every* one of those
# records; the four below did, so they can be filled in without re-reading the
# code. A record may still earn a second label on top of the one listed, and
# often does: `destroy-original` also drew `code-destroyed` on 14 of its 16, and
# `too-few-conditions` also drew `wrong-exception-handling` on 6 of its 24.
#
# `wrong-property` and `wrong-range` are deliberately absent. They say what a
# guard inspects, not which way the two throwing sets differ, so they split
# across `too-strict` and `too-lenient` (24 of 26 and 37 of 40 went to
# `too-lenient`, the rest did not) and have to be decided per record. Those are
# the ones worth opening the code for.
#
# The pre-taxonomy spellings (`no-enought-ebt`, `overcatch`, `always-throws`,
# `fits-test-input`, `wrong-exception-type`, `location`) are gone from every
# store. Were one to come back it would still read fine and the form would still
# offer it, because `/api/commentor/tags` adds every category already present in
# the stores to the options above.
RETIRED_CATEGORY_MIGRATION: dict[str, str] = {
    "destroy-original": "too-strict",
    "too-many-conditions": "too-strict",
    "too-few-conditions": "too-lenient",
    "wrong-location": "wrong-exception-handling",
}


ANNOTATION_DIR: Path = ThrowgenMacros.annotations_dir


def entry_categories(values: dict[str, Any], field_name: str = "category") -> list[str]:
    """Read a category field that may hold one category or several.

    The viewer used to offer a single category per entry and now offers a list,
    so a store holds both shapes: the annotations made before the change carry a
    string, the ones made after carry a list. Both read back as a list here, in
    the order they were entered and without duplicates or blanks. Spaces become
    hyphens, since the paper's macros are keyed by the hyphenated spelling.
    """
    raw = values.get(field_name)
    if raw is None:
        return []
    items = raw if isinstance(raw, (list, tuple)) else [raw]

    categories: list[str] = []
    for item in items:
        category = str(item).strip().replace(" ", "-")
        if category and category not in categories:
            categories.append(category)
    return categories


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def path_slug(file_path: str) -> str:
    """Turn a result file path into a flat file name usable as a store key."""
    rel = file_path
    if Path(rel).is_absolute():
        try:
            rel = str(Path(rel).resolve().relative_to(ExlongMacros.project_dir))
        except ValueError:
            rel = Path(rel).name
    rel = rel.strip("/")
    if rel.endswith(".jsonl"):
        rel = rel[: -len(".jsonl")]
    return rel.replace("/", "__")


def store_path(commentor_id: str, file_path: str) -> Path:
    """Path of the annotation file backing ``file_path`` for ``commentor_id``."""
    return ANNOTATION_DIR / commentor_id / f"{path_slug(file_path)}.jsonl"


def load_annotations(commentor_id: str, file_path: str) -> dict[int, dict[str, Any]]:
    """Load all annotations for a result file, keyed by record index."""
    path = store_path(commentor_id, file_path)
    if not path.exists():
        return {}

    annotations: dict[int, dict[str, Any]] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            annotations[int(record["record_index"])] = record
    return annotations


def save_annotation(
    commentor_id: str,
    file_path: str,
    record_index: int,
    entries: list[dict[str, Any]],
    data_id: str | None = None,
) -> dict[str, Any]:
    """Insert, update, or delete the annotation of a single record.

    Passing an empty ``entries`` list removes the record's annotation, so the
    store never keeps rows that the annotator has cleared.

    Returns the stored record (or an empty one when the annotation was removed).
    """
    annotations = load_annotations(commentor_id, file_path)
    existing = annotations.get(record_index)

    if entries:
        record = {
            "record_index": record_index,
            "data_id": (
                data_id if data_id is not None else (existing or {}).get("data_id")
            ),
            "entries": entries,
            "created_at": (existing or {}).get("created_at", _now()),
            "updated_at": _now(),
        }
        annotations[record_index] = record
    else:
        annotations.pop(record_index, None)
        record = {
            "record_index": record_index,
            "data_id": data_id,
            "entries": [],
            "created_at": None,
            "updated_at": None,
        }

    path = store_path(commentor_id, file_path)
    su.io.mkdir(path.parent)
    su.io.dump(path, [annotations[i] for i in sorted(annotations)])
    return record


def collect_tags(commentor_id: str, field_name: str) -> list[str]:
    """Collect every value the annotator has used for a tag field so far."""
    root = ANNOTATION_DIR / commentor_id
    if not root.exists():
        return []

    tags: set[str] = set()
    for path in root.glob("*.jsonl"):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                for entry in record.get("entries", []):
                    value = entry.get("values", {}).get(field_name)
                    # A field may hold one value or a list of them; a tag field
                    # that allows several contributes each of them separately.
                    values = value if isinstance(value, (list, tuple)) else [value]
                    for item in values:
                        if isinstance(item, str) and item.strip():
                            tags.add(item.strip())
    return sorted(tags)


def qual_samples(
    file_path: str, commentor_id: str = QUAL_COMMENTOR_ID
) -> list[dict[str, Any]]:
    """Read qualitative annotations back in the shape the analysis expects.

    Collapses the per-record entries into the ``{data_id, semantic_match,
    categories}`` records that ``qualitative_analysis.compute_summary`` and the
    markdown parser both produce. An \\ERC is a false positive as soon as one of
    its entries says the code is not equivalent, and its categories are the
    union of the categories across its entries.

    Reads the paper's own store by default; pass ``commentor_id`` to read
    another annotator's, which is what the inter-annotator agreement in
    ``qualitative_analysis.run_agreement`` does.
    """
    samples: list[dict[str, Any]] = []
    for _, record in sorted(load_annotations(commentor_id, file_path).items()):
        data_id = record.get("data_id")
        if not data_id:
            continue

        matches = [
            str(entry.get("values", {}).get("semantic_match", "")).strip().lower()
            for entry in record.get("entries", [])
        ]
        matches = [m for m in matches if m in ("yes", "no")]
        semantic_match = all(m == "yes" for m in matches) if matches else None

        categories: list[str] = []
        for entry in record.get("entries", []):
            for category in entry_categories(entry.get("values", {})):
                if category not in categories:
                    categories.append(category)

        # A record decided by mechanical rule rather than by inspection carries
        # a note ending in "[auto]". It counts for the store's verdict -- the
        # \ERC would have scored equivalent anyway -- but not for agreement
        # between annotators, which is over what they actually decided.
        auto = any(
            str(entry.get("values", {}).get("note", "")).strip().endswith("[auto]")
            for entry in record.get("entries", [])
        )

        samples.append(
            {
                "data_id": data_id,
                "semantic_match": semantic_match,
                "categories": categories,
                "auto": auto,
            }
        )
    return samples
