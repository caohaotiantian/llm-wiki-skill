#!/usr/bin/env python3
"""
Graph analysis for the wiki knowledge base using NetworkX.

Builds a directed graph from typed links in YAML frontmatter and wikilinks
in prose, then exposes subcommands for exploration and analysis.

Usage:
    python graph.py <vault-path> neighbors <slug> --depth 2
    python graph.py <vault-path> path <from> <to>
    python graph.py <vault-path> centrality --metric pagerank --limit 10
    python graph.py <vault-path> communities
    python graph.py <vault-path> orphans
    python graph.py <vault-path> stats
    python graph.py <vault-path> stats --format json
    python graph.py <vault-path> stats --export html -o graph.html
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import networkx as nx


# ---------------------------------------------------------------------------
# Parsing helpers (self-contained — no imports from lint_links.py)
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(
    r"^---\s*\n(.*?)\n(?:---|\.\.\.)(?:\s*\n|$)", re.DOTALL
)

_TYPED_LINK_RE = re.compile(
    r"""\{\s*target\s*:\s*"([^"]+)"\s*,\s*type\s*:\s*"([^"]+)"\s*\}"""
)

_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")


def _extract_frontmatter(content: str) -> str | None:
    """Return the raw YAML frontmatter block, or None."""
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    m = _FRONTMATTER_RE.match(content)
    return m.group(1) if m else None


def _frontmatter_field(fm: str, field: str) -> str | None:
    """Return the raw value string for a simple top-level YAML key."""
    for line in fm.splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{field}:"):
            return stripped[len(field) + 1 :].strip()
    return None


def _parse_typed_links_from_file(file_path: str) -> list[dict]:
    """Parse typed links from a markdown file's YAML frontmatter.

    Expects ``links: [{target: "slug", type: "type"}, ...]`` inside the
    frontmatter block.  Returns a list of ``{"target": ..., "type": ...}``
    dicts.
    """
    try:
        content = Path(file_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    fm = _extract_frontmatter(content)
    if fm is None:
        return []

    results: list[dict] = []
    in_links = False
    for line in fm.splitlines():
        stripped = line.strip()
        if stripped.startswith("links:"):
            in_links = True
            # inline list on same line?
            for m in _TYPED_LINK_RE.finditer(stripped):
                results.append({"target": m.group(1), "type": m.group(2)})
            continue
        if in_links:
            # End of links block when we hit a new top-level key
            if re.match(r"^[a-zA-Z_]", line) and not line.startswith(" "):
                break
            for m in _TYPED_LINK_RE.finditer(stripped):
                results.append({"target": m.group(1), "type": m.group(2)})
    return results


def _parse_tags_from_frontmatter(fm: str) -> list[str]:
    """Extract tags list from frontmatter."""
    val = _frontmatter_field(fm, "tags")
    if not val:
        return []
    # inline list: [a, b, c]
    if val.startswith("["):
        inner = val.strip("[]")
        return [t.strip().strip("\"'") for t in inner.split(",") if t.strip()]
    return []


def _parse_title_from_frontmatter(fm: str) -> str | None:
    val = _frontmatter_field(fm, "title")
    if val:
        return val.strip("\"'")
    return None


def _scan_wikilinks(file_path: str) -> list[str]:
    """Extract wikilink targets from prose (outside frontmatter, code blocks, inline code)."""
    try:
        content = Path(file_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    content = content.replace("\r\n", "\n").replace("\r", "\n")
    # Strip frontmatter
    m = _FRONTMATTER_RE.match(content)
    body = content[m.end():] if m else content

    # Strip referenced-by blocks
    body = re.sub(
        r"<!-- referenced-by:start -->.*?<!-- referenced-by:end -->",
        "", body, flags=re.DOTALL,
    )

    targets = []
    code_fence = ""
    for line in body.split("\n"):
        stripped = line.strip()
        # Track fenced code blocks
        if not code_fence:
            fence_match = re.match(r"^(`{3,}|~{3,})", stripped)
            if fence_match:
                code_fence = fence_match.group(1)
                continue
        else:
            fence_char = code_fence[0]
            if re.match(r"^" + re.escape(fence_char) + r"{" + str(len(code_fence)) + r",}\s*$", stripped):
                code_fence = ""
            continue
        # Strip inline code spans before scanning
        scannable = re.sub(r"`[^`]+`", "", line)
        for raw in _WIKILINK_RE.findall(scannable):
            # Strip pipe syntax and heading anchors
            target = raw.split("|")[0].split("#")[0].strip()
            if target:
                targets.append(target)
    return targets


def _slug_from_path(file_path: str) -> str:
    """Derive slug from filename (stem)."""
    return Path(file_path).stem


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def build_graph(vault_path: str | Path) -> nx.DiGraph:
    """Scan *vault_path*/wiki/ for .md files and build a NetworkX DiGraph.

    Nodes carry ``title``, ``tags``, ``node_type`` attributes.
    Edges carry a ``link_type`` attribute.
    """
    vault_path = Path(vault_path)
    wiki_dir = vault_path / "wiki"
    g = nx.DiGraph()

    if not wiki_dir.is_dir():
        return g

    md_files = sorted(
        f for f in wiki_dir.rglob("*.md") if not f.name.endswith(".snapshot.md")
    )
    # First pass: register nodes
    for fp in md_files:
        slug = _slug_from_path(str(fp))
        content = fp.read_text(encoding="utf-8", errors="replace")
        fm = _extract_frontmatter(content)
        tags = _parse_tags_from_frontmatter(fm) if fm else []
        title = (_parse_title_from_frontmatter(fm) if fm else None) or slug
        node_type = tags[0] if tags else "default"
        g.add_node(slug, title=title, tags=tags, node_type=node_type)

    # Second pass: edges from typed links
    for fp in md_files:
        slug = _slug_from_path(str(fp))
        typed = _parse_typed_links_from_file(str(fp))
        for link in typed:
            target = link["target"]
            # Ensure target node exists
            if target not in g:
                g.add_node(target, title=target, tags=[], node_type="default")
            g.add_edge(slug, target, link_type=link["type"])

    # Third pass: wikilinks as fallback edges
    for fp in md_files:
        slug = _slug_from_path(str(fp))
        wikilinks = _scan_wikilinks(str(fp))
        for target in wikilinks:
            if target == slug:
                continue
            if not g.has_edge(slug, target):
                if target not in g:
                    g.add_node(target, title=target, tags=[], node_type="default")
                g.add_edge(slug, target, link_type="references")

    return g


# ---------------------------------------------------------------------------
# Subcommand implementations
# ---------------------------------------------------------------------------

def find_neighbors(
    g: nx.DiGraph, slug: str, depth: int = 1
) -> list[dict[str, Any]]:
    """Return pages within *depth* hops of *slug*.

    Each result is ``{"slug": ..., "distance": ..., "link_type": ...}``.
    """
    if slug not in g:
        return []
    undirected = g.to_undirected(as_view=True)
    lengths = nx.single_source_shortest_path_length(undirected, slug, cutoff=depth)
    results: list[dict[str, Any]] = []
    for node, dist in sorted(lengths.items(), key=lambda x: x[1]):
        if node == slug:
            continue
        # Determine link type from direct edge if present
        lt = ""
        if g.has_edge(slug, node):
            lt = g.edges[slug, node].get("link_type", "")
        elif g.has_edge(node, slug):
            lt = g.edges[node, slug].get("link_type", "")
        results.append({"slug": node, "distance": dist, "link_type": lt})
    return results


def find_shortest_path(
    g: nx.DiGraph, source: str, target: str
) -> list[dict[str, Any]] | None:
    """Find shortest path from *source* to *target*.

    Returns an ordered list of ``{"slug": ..., "link_type": ...}`` or
    ``None`` if no path exists.
    """
    if source not in g or target not in g:
        return None
    try:
        nodes = nx.shortest_path(g, source, target)
    except nx.NetworkXNoPath:
        return None

    result: list[dict[str, Any]] = []
    for i, node in enumerate(nodes):
        lt = ""
        if i > 0:
            lt = g.edges[nodes[i - 1], node].get("link_type", "")
        result.append({"slug": node, "link_type": lt})
    return result


def compute_centrality(
    g: nx.DiGraph, metric: str = "pagerank", limit: int = 20
) -> list[dict[str, Any]]:
    """Rank pages by importance using the given *metric*.

    Returns ``[{"slug": ..., "score": ...}, ...]`` sorted descending.
    """
    if g.number_of_nodes() == 0:
        return []

    if metric == "pagerank":
        scores = nx.pagerank(g)
    elif metric == "degree":
        scores = dict(g.degree())
    elif metric == "betweenness":
        scores = nx.betweenness_centrality(g)
    elif metric == "eigenvector":
        try:
            scores = nx.eigenvector_centrality(g, max_iter=1000)
        except nx.PowerIterationFailedConvergence:
            scores = nx.eigenvector_centrality_numpy(g)
    else:
        raise ValueError(f"Unknown metric: {metric}")

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [{"slug": s, "score": round(v, 6)} for s, v in ranked[:limit]]


def detect_communities(
    g: nx.DiGraph, algorithm: str = "louvain"
) -> list[list[str]]:
    """Detect topical clusters.  Returns list of communities (each a list of slugs)."""
    if g.number_of_nodes() == 0:
        return []

    ug = g.to_undirected()

    if algorithm == "louvain":
        try:
            comms = nx.community.louvain_communities(ug)
        except Exception:
            comms = nx.community.label_propagation_communities(ug)
    elif algorithm == "label_propagation":
        comms = nx.community.label_propagation_communities(ug)
    else:
        raise ValueError(f"Unknown algorithm: {algorithm}")

    return [sorted(c) for c in comms]


def find_orphans(g: nx.DiGraph) -> list[str]:
    """Return slugs with no incoming and no outgoing edges."""
    return sorted(
        n for n in g.nodes() if g.in_degree(n) == 0 and g.out_degree(n) == 0
    )


def graph_stats(g: nx.DiGraph) -> dict[str, Any]:
    """Return basic graph statistics."""
    ug = g.to_undirected()
    n = g.number_of_nodes()
    return {
        "nodes": n,
        "edges": g.number_of_edges(),
        "connected_components": nx.number_connected_components(ug) if n else 0,
        "density": round(nx.density(g), 6) if n else 0,
        "avg_degree": round(sum(d for _, d in g.degree()) / n, 4) if n else 0,
    }


# ---------------------------------------------------------------------------
# HTML / Cytoscape export
# ---------------------------------------------------------------------------

_NODE_COLORS = {
    "concept": "#e74c3c",
    "entity": "#3498db",
    "topic": "#2ecc71",
    "source": "#e67e22",
    "query": "#9b59b6",
    "default": "#95a5a6",
}


def export_html(g: nx.DiGraph) -> str:
    """Generate a self-contained HTML page with Cytoscape.js visualisation."""

    elements: list[dict] = []
    node_types: set[str] = set()

    for node, data in g.nodes(data=True):
        nt = data.get("node_type", "default")
        node_types.add(nt)
        elements.append(
            {
                "group": "nodes",
                "data": {
                    "id": node,
                    "label": data.get("title", node),
                    "node_type": nt,
                    "tags": data.get("tags", []),
                    "color": _NODE_COLORS.get(nt, _NODE_COLORS["default"]),
                },
            }
        )

    for u, v, data in g.edges(data=True):
        elements.append(
            {
                "group": "edges",
                "data": {
                    "source": u,
                    "target": v,
                    "link_type": data.get("link_type", ""),
                },
            }
        )

    elements_json = json.dumps(elements, indent=2)
    node_types_json = json.dumps(sorted(node_types))

    html = f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Wiki Graph</title>
<script src="https://unpkg.com/cytoscape@3/dist/cytoscape.min.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: sans-serif; display: flex; height: 100vh; }}
  #cy {{ flex: 1; }}
  #sidebar {{ width: 280px; background: #f5f5f5; padding: 12px; overflow-y: auto;
              border-left: 1px solid #ccc; display: none; }}
  #sidebar h3 {{ margin-bottom: 8px; }}
  #sidebar p {{ margin: 4px 0; font-size: 13px; }}
  #controls {{ position: absolute; top: 10px; left: 10px; background: #fff;
               padding: 10px; border-radius: 6px; box-shadow: 0 1px 4px rgba(0,0,0,.2);
               z-index: 10; font-size: 13px; }}
  #controls label {{ display: block; margin: 2px 0; }}
  #search {{ width: 100%; margin-bottom: 6px; padding: 4px; }}
</style>
</head>
<body>
<div id="controls">
  <input id="search" type="text" placeholder="Search nodes..."/>
  <div id="filters"></div>
</div>
<div id="cy"></div>
<div id="sidebar">
  <h3 id="sb-title"></h3>
  <p id="sb-type"></p>
  <p id="sb-tags"></p>
  <p id="sb-edges"></p>
</div>
<script>
var elements = {elements_json};
var nodeTypes = {node_types_json};

// build filter checkboxes
var filtersDiv = document.getElementById('filters');
nodeTypes.forEach(function(t) {{
  var lbl = document.createElement('label');
  var cb = document.createElement('input');
  cb.type = 'checkbox'; cb.checked = true; cb.value = t;
  cb.addEventListener('change', applyFilters);
  lbl.appendChild(cb);
  lbl.appendChild(document.createTextNode(' ' + t));
  filtersDiv.appendChild(lbl);
}});

var cy = cytoscape({{
  container: document.getElementById('cy'),
  elements: elements,
  style: [
    {{ selector: 'node', style: {{
        'label': 'data(label)', 'background-color': 'data(color)',
        'font-size': 10, 'text-valign': 'bottom', 'text-margin-y': 4,
        'width': 20, 'height': 20 }} }},
    {{ selector: 'edge', style: {{
        'width': 1, 'line-color': '#aaa', 'target-arrow-color': '#aaa',
        'target-arrow-shape': 'triangle', 'curve-style': 'bezier',
        'font-size': 8 }} }},
    {{ selector: '.hidden', style: {{ 'display': 'none' }} }}
  ],
  layout: {{ name: 'cose', animate: false }}
}});

cy.on('tap', 'node', function(evt) {{
  var d = evt.target.data();
  document.getElementById('sidebar').style.display = 'block';
  document.getElementById('sb-title').textContent = d.label;
  document.getElementById('sb-type').textContent = 'Type: ' + d.node_type;
  document.getElementById('sb-tags').textContent = 'Tags: ' + (d.tags||[]).join(', ');
  var edges = evt.target.connectedEdges().map(function(e) {{
    return e.data('source') + ' -[' + e.data('link_type') + ']-> ' + e.data('target');
  }});
  document.getElementById('sb-edges').textContent = 'Edges: ' + edges.join('; ');
}});

document.getElementById('search').addEventListener('input', applyFilters);

function applyFilters() {{
  var q = document.getElementById('search').value.toLowerCase();
  var checked = [];
  filtersDiv.querySelectorAll('input').forEach(function(cb) {{
    if (cb.checked) checked.push(cb.value);
  }});
  cy.nodes().forEach(function(n) {{
    var d = n.data();
    var typeOk = checked.indexOf(d.node_type) !== -1;
    var searchOk = !q || d.label.toLowerCase().indexOf(q) !== -1 || d.id.toLowerCase().indexOf(q) !== -1;
    if (typeOk && searchOk) n.removeClass('hidden'); else n.addClass('hidden');
  }});
  cy.edges().forEach(function(e) {{
    if (e.source().hasClass('hidden') || e.target().hasClass('hidden'))
      e.addClass('hidden'); else e.removeClass('hidden');
  }});
}}
</script>
</body>
</html>
"""
    return html


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt_table(rows: list[dict], keys: list[str]) -> str:
    """Render a list of dicts as a markdown table."""
    if not rows:
        return "(no results)"
    widths = {k: max(len(k), *(len(str(r.get(k, ""))) for r in rows)) for k in keys}
    header = "| " + " | ".join(k.ljust(widths[k]) for k in keys) + " |"
    sep = "| " + " | ".join("-" * widths[k] for k in keys) + " |"
    lines = [header, sep]
    for r in rows:
        lines.append("| " + " | ".join(str(r.get(k, "")).ljust(widths[k]) for k in keys) + " |")
    return "\n".join(lines)


def _output(data: Any, fmt: str, table_keys: list[str] | None = None) -> str:
    if fmt == "json":
        return json.dumps(data, indent=2)
    if isinstance(data, list) and table_keys:
        return _fmt_table(data, table_keys)
    if isinstance(data, dict):
        return "\n".join(f"{k}: {v}" for k, v in data.items())
    return str(data)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    # Common flags shared by all subcommands
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--format", choices=["markdown", "json"], default="markdown")
    common.add_argument("--export", choices=["html"], default=None)
    common.add_argument("-o", "--output", default=None, help="Output file path")

    parser = argparse.ArgumentParser(description="Wiki graph analysis")
    parser.add_argument("vault", help="Path to the vault root")

    sub = parser.add_subparsers(dest="command")

    p_nb = sub.add_parser("neighbors", help="Pages within N hops", parents=[common])
    p_nb.add_argument("slug")
    p_nb.add_argument("--depth", type=int, default=1)

    p_pa = sub.add_parser("path", help="Shortest path between two pages", parents=[common])
    p_pa.add_argument("source")
    p_pa.add_argument("target")

    p_ce = sub.add_parser("centrality", help="Rank pages by importance", parents=[common])
    p_ce.add_argument("--metric", choices=["pagerank", "degree", "betweenness", "eigenvector"], default="pagerank")
    p_ce.add_argument("--limit", type=int, default=20)

    p_cm = sub.add_parser("communities", help="Detect topical clusters", parents=[common])
    p_cm.add_argument("--algorithm", choices=["louvain", "label_propagation"], default="louvain")

    sub.add_parser("orphans", help="Pages with no links", parents=[common])
    sub.add_parser("stats", help="Graph statistics", parents=[common])

    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        sys.exit(1)

    g = build_graph(args.vault)

    # Handle HTML export
    if args.export == "html":
        html = export_html(g)
        if args.output:
            Path(args.output).write_text(html, encoding="utf-8")
            print(f"Exported to {args.output}")
        else:
            print(html)
        return

    result: Any = None
    table_keys: list[str] | None = None

    if args.command == "neighbors":
        result = find_neighbors(g, args.slug, depth=args.depth)
        table_keys = ["slug", "distance", "link_type"]
    elif args.command == "path":
        result = find_shortest_path(g, args.source, args.target)
        if result is None:
            result = []
        table_keys = ["slug", "link_type"]
    elif args.command == "centrality":
        result = compute_centrality(g, metric=args.metric, limit=args.limit)
        table_keys = ["slug", "score"]
    elif args.command == "communities":
        comms = detect_communities(g, algorithm=args.algorithm)
        result = [{"community": i, "members": ", ".join(c)} for i, c in enumerate(comms)]
        table_keys = ["community", "members"]
    elif args.command == "orphans":
        result = [{"slug": s} for s in find_orphans(g)]
        table_keys = ["slug"]
    elif args.command == "stats":
        result = graph_stats(g)

    output = _output(result, args.format, table_keys)
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"Written to {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
