import json
from pathlib import Path

from dreamgraph.bench import EXPORT

ROOT = Path(__file__).resolve().parents[1]


def test_readme_quotes_the_export_and_labels_the_noise():
    readme = (ROOT / "README.md").read_text()
    summary = json.loads(EXPORT.read_text())
    dream = summary["series"]["dreamgraph"]["accuracy"]
    # The table uses one decimal, the same rounding the dashboard prints.
    assert f"{dream[-1] * 100:.1f}" in readme
    assert f"{dream[3] * 100:.1f}" in readme
    assert "synthetic" in readme.lower()
    assert "live_engine" in readme
    assert "hydradb" in readme
    assert "Dict learner" in readme
    assert "3-hop" in readme
    assert "Zenodo" in readme
    assert "H12" in readme
    assert "PASS" in readme
    assert "68.2" in readme
    assert "15 rollbacks" in readme
    posts = (ROOT / "docs" / "POSTS.md").read_text()
    assert "@hydra_db" in posts
    assert "Not posted" in posts
