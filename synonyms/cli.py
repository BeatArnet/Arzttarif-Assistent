import argparse
import json
import sys
from pathlib import Path
from typing import List
import logging

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "synonyms"

from . import generator, storage
from .models import SynonymCatalog, SynonymEntry


def generate(args: argparse.Namespace) -> None:
    """Generate synonym suggestions and write them as JSON."""

    if hasattr(sys.stdout, "reconfigure"):
        getattr(sys.stdout, "reconfigure")(encoding="utf-8")

    entries = generator.extract_base_terms_from_tariff()
    base_terms = entries

    catalog = storage.load_synonyms(args.existing) if args.existing else SynonymCatalog()

    # auto-resume when output file already contains entries and --start was not specified
    if args.output and args.start == 0 and not args.existing and Path(args.output).exists():
        catalog = storage.load_synonyms(args.output)
        args.start = len(catalog.entries)

    processed = 0

    for entry in generator.propose_synonyms_incremental(
        base_terms,
        start=args.start,
    ):
        catalog.entries[entry.base_term] = entry
        processed += 1
        if args.output and processed % args.batch_size == 0:
            storage.save_synonyms(catalog, args.output)
        logging.info("%s -> %s", entry.base_term, ", ".join(entry.synonyms))

    if args.output:
        storage.save_synonyms(catalog, args.output)
    else:
        data = {base: entry.synonyms for base, entry in catalog.entries.items()}
        sys.stdout.buffer.write(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))


def validate(args: argparse.Namespace) -> None:
    """Validate synonym data from a JSON file."""

    catalog = storage.load_synonyms(args.input)
    try:
        storage.validate_catalog(catalog)
    except ValueError as e:
        raise SystemExit(f"invalid catalog: {e}")

    print(f"Catalog '{args.input}' OK")


def stats(args: argparse.Namespace) -> None:
    """Show statistics about synonyms."""

    catalog = storage.load_synonyms(args.input)
    total_entries = len(catalog.entries)
    total_synonyms = sum(len(e.synonyms) for e in catalog.entries.values())

    print(f"Entries: {total_entries}")
    print(f"Synonyms: {total_synonyms}")


def export(args: argparse.Namespace) -> None:
    """Export synonym data as a plain text file."""

    catalog = storage.load_synonyms(args.input)
    lines = []
    for base, entry in catalog.entries.items():
        if entry.synonyms:
            line = f"{base}: {', '.join(entry.synonyms)}"
            lines.append(line)
        else:
            lines.append(base)

    path = args.output or Path("-")
    if path == Path("-"):
        for line in lines:
            print(line)
    else:
        Path(path).write_text("\n".join(lines), encoding="utf-8")




def main(argv: List[str] | None = None) -> None:
    if argv is None and len(sys.argv) == 1:
        argv = ["generate", "--output", "data/synonyms.json"]
    parser = argparse.ArgumentParser(description="Synonyms utility")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("generate", help="generate synonym suggestions")
    p.add_argument(
        "--existing",
        type=Path,
        default=None,
        help="optional existing catalog to merge with",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help="write result to this file instead of stdout",
    )
    p.add_argument(
        "--start",
        type=int,
        default=0,
        help="start index in base terms",
    )
    p.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="number of entries after which to update output file",
    )
    p.set_defaults(func=generate)


    p = sub.add_parser("validate", help="validate synonym data")
    p.add_argument("input", type=Path)
    p.set_defaults(func=validate)

    p = sub.add_parser("stats", help="show statistics")
    p.add_argument("input", type=Path)
    p.set_defaults(func=stats)

    p = sub.add_parser("export", help="export synonym data")
    p.add_argument("input", type=Path)
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help="output file (defaults to stdout)",
    )
    p.set_defaults(func=export)

    parser.add_argument("-v", "--verbose", action="count", default=0, help="increase verbosity")
    parser.add_argument("--log-file", type=Path, default=None, help="write logs to this file")

    args = parser.parse_args(argv)

    level = logging.WARNING
    if args.verbose == 1:
        level = logging.INFO
    elif args.verbose >= 2:
        level = logging.DEBUG

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if args.log_file:
        handlers.append(logging.FileHandler(args.log_file, encoding="utf-8"))

    logging.basicConfig(level=level, format="%(levelname)s: %(message)s", handlers=handlers)

    args.func(args)


if __name__ == "__main__":
    main()
