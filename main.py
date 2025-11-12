import argparse

def arguments():
    parser = argparse.ArgumentParser(
        prog="CIPS Excel normalizer",
        description="Normalize all CIPS Excel sheets.",
    )
    parser.add_argument(
        "-f",
        "--file",
        help="File or directory to normalize",
        type=str,
    )
    parser.add_argument(
        "-o",
        "--overwrite",
        action="store_true",
        default=False,
        help="Overwrite existing files",
    )
    parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        default=False,
        help="Output also as JSON",
    )

    return parser.parse_args()

def main():
    return None

if __name__ == "__main__":
    main()