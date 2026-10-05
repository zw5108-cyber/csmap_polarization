"""Export a scoped research query to CSV or NDJSON."""

import argparse
from pathlib import Path

from csmap_client import CsmapClient, CsmapError


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subreddit", required=True)
    parser.add_argument("--after", required=True)
    parser.add_argument("--before", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--keywords")
    parser.add_argument("--author")
    parser.add_argument("--type", choices=("posts", "comments"), default="posts")
    parser.add_argument("--min-score", type=int)
    parser.add_argument("--url")
    parser.add_argument("--api-key-file", type=Path)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    options = {
        "subreddit": args.subreddit,
        "author": args.author,
        "after": args.after,
        "before": args.before,
        "min_score": args.min_score,
        "overwrite": args.overwrite,
    }
    try:
        client = CsmapClient(base_url=args.url, api_key_file=args.api_key_file, timeout=args.timeout)
        if args.keywords:
            path = client.export_search(args.keywords, args.output, type=args.type, **options)
        else:
            path = client.export(args.type, args.output, **options)
    except (CsmapError, ValueError, TypeError, OSError) as error:
        parser.exit(1, f"Export failed: {error}\n")
    print(f"Exported to {path}")


if __name__ == "__main__":
    main()
