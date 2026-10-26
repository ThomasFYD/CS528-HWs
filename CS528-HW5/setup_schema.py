#!/usr/bin/env python3
"""Create missing tables without deleting existing homework evidence."""
import argparse
import json
from database import create_database


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local", action="store_true", help="Use gcloud login on the laptop")
    args = parser.parse_args()
    db = create_database(local=args.local)
    try:
        print(json.dumps(db.setup()))
    finally:
        db.close()


if __name__ == "__main__":
    main()
