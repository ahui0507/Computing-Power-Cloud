"""Versioned filesystem layout frozen in each allocation's creation options."""

LEGACY_LAYOUT = "legacy"
SEPARATE_LAYOUT = "separate-v1"
WORKSPACE_PATH = "/workspace"
PERSISTENT_PATH = "/data"


def persistent_path(options):
    return PERSISTENT_PATH if options.get("storage_layout") == SEPARATE_LAYOUT else WORKSPACE_PATH
