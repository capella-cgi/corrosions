import os


def resolve_output_dir(output_dir: str | None = None) -> str:
    """Resolve and create the output directory, defaulting to ``<cwd>/output``."""
    if output_dir is None:
        output_dir = os.path.join(os.getcwd(), "output")

    os.makedirs(output_dir, exist_ok=True)
    return output_dir
