#!/usr/bin/env python3
"""Tests for graph.py."""

import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "llm-wiki", "scripts"))

from graph import (
    build_graph,
    find_neighbors,
    find_shortest_path,
    compute_centrality,
    detect_communities,
    find_orphans,
    graph_stats,
    export_html,
)


def _make_wiki(tmp_path):
    """Create a small wiki with typed links for testing."""
    wiki = tmp_path / "wiki"
    wiki.mkdir()

    (wiki / "concept-a.md").write_text(
        '''---
tags: [concept]
title: Concept A
links:
  - {target: "concept-b", type: "references"}
  - {target: "entity-x", type: "depends_on"}
---

# Concept A

Content about concept A with [[concept-b]] reference.
'''
    )

    (wiki / "concept-b.md").write_text(
        '''---
tags: [concept]
title: Concept B
links:
  - {target: "concept-a", type: "references"}
---

# Concept B

Content about concept B.
'''
    )

    (wiki / "entity-x.md").write_text(
        '''---
tags: [entity]
title: Entity X
links:
  - {target: "concept-a", type: "mentions"}
---

# Entity X

An entity page.
'''
    )

    (wiki / "orphan.md").write_text(
        '''---
tags: [concept]
title: Orphan Page
---

# Orphan

No links at all.
'''
    )

    return tmp_path


def test_build_graph(tmp_path):
    vault = _make_wiki(tmp_path)
    g = build_graph(vault)
    assert g.number_of_nodes() >= 3
    assert g.number_of_edges() >= 3


def test_find_neighbors(tmp_path):
    vault = _make_wiki(tmp_path)
    g = build_graph(vault)
    neighbors = find_neighbors(g, "concept-a", depth=1)
    slugs = [n["slug"] for n in neighbors]
    assert "concept-b" in slugs
    assert "entity-x" in slugs


def test_find_neighbors_depth2(tmp_path):
    vault = _make_wiki(tmp_path)
    g = build_graph(vault)
    neighbors = find_neighbors(g, "concept-a", depth=2)
    assert len(neighbors) >= 2


def test_find_shortest_path(tmp_path):
    vault = _make_wiki(tmp_path)
    g = build_graph(vault)
    path = find_shortest_path(g, "entity-x", "concept-b")
    assert path is not None
    assert len(path) >= 2


def test_find_shortest_path_no_path(tmp_path):
    vault = _make_wiki(tmp_path)
    g = build_graph(vault)
    path = find_shortest_path(g, "orphan", "concept-a")
    assert path is None or len(path) == 0


def test_compute_centrality(tmp_path):
    vault = _make_wiki(tmp_path)
    g = build_graph(vault)
    ranking = compute_centrality(g, metric="degree", limit=10)
    assert len(ranking) > 0
    assert all("slug" in r and "score" in r for r in ranking)


def test_compute_centrality_pagerank(tmp_path):
    vault = _make_wiki(tmp_path)
    g = build_graph(vault)
    ranking = compute_centrality(g, metric="pagerank", limit=10)
    assert len(ranking) > 0


def test_detect_communities(tmp_path):
    vault = _make_wiki(tmp_path)
    g = build_graph(vault)
    communities = detect_communities(g)
    assert isinstance(communities, list)
    assert len(communities) >= 1


def test_find_orphans(tmp_path):
    vault = _make_wiki(tmp_path)
    g = build_graph(vault)
    orphans = find_orphans(g)
    assert "orphan" in orphans


def test_graph_stats(tmp_path):
    vault = _make_wiki(tmp_path)
    g = build_graph(vault)
    stats = graph_stats(g)
    assert "nodes" in stats
    assert "edges" in stats
    assert stats["nodes"] >= 3


def test_export_html(tmp_path):
    vault = _make_wiki(tmp_path)
    g = build_graph(vault)
    html = export_html(g)
    assert "cytoscape" in html.lower()
    assert "concept-a" in html
    assert "<html" in html.lower()


def test_build_graph_empty(tmp_path):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    g = build_graph(tmp_path)
    assert g.number_of_nodes() == 0
