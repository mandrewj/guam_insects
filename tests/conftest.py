"""Shared fixtures: a small dataset (the Oryctes world) as CSV files in tests/fixtures/dataset.

    Hexapoda L2655 > Insecta H6 > Coleoptera C2L > Scarabaeidae SCARB > Oryctes ORYCT
        > O. rhinoceros ORRHI, O. gigas ORGIG, O. marianus gbif:777 (not in COL, with a
        spelling variant name-3);  > Callirhipidae CALLI > Callirhipis CALIS > C. onoi name-2
    merged names: Rhipiceridae into Callirhipidae, Scarabaeus rhinoceros into ORRHI (COL synonym).
    One document (d1), a machine-read literature row and a machine-written note on ORGIG, one
    unplaced name.
"""

import shutil

import pytest

from guaminsects import config, ids

C = ids.from_col
FIXTURE = config.ROOT / "tests" / "fixtures" / "dataset"


@pytest.fixture
def world(tmp_path):
    """A writable copy of the fixture dataset."""
    out = tmp_path / "dataset"
    shutil.copytree(FIXTURE, out)
    return out
