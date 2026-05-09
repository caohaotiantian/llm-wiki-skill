"""Tests for v2 footnote lint rules (L-1..L-4) + format_version dispatch."""

import os
import sys
import textwrap

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "llm-wiki", "scripts"))

from frontmatter import parse as parse_fm
from lint_links import run_all_checks


def _split(content: str):
    """Helper: parse frontmatter dict + body string from a synthetic page."""
    fm, body = parse_fm(content)
    return fm, body


# ---------------------------------------------------------------------------
# L-1: every [^id] reference has a matching [^id]: definition
# ---------------------------------------------------------------------------

def test_footnote_l1_ref_without_def_legacy_skipped(tmp_path):
    """Legacy page (no format_version: 2) with unbalanced [^foo] ref: NOT reported."""
    page = tmp_path / "wiki" / "page.md"
    page.parent.mkdir(parents=True)
    content = textwrap.dedent("""\
        ---
        updated: 2025-05-01
        ---

        # Page

        A claim about something[^foo].
    """)
    page.write_text(content)
    fm, body = _split(content)

    violations = run_all_checks(str(page), body, fm)

    rule_codes = [v.get("rule") for v in violations]
    assert "L-1" not in rule_codes, (
        f"Legacy page should not produce L-1 violations, got: {violations}"
    )


def test_footnote_l1_ref_without_def_v2_reported(tmp_path):
    """v2 page with unbalanced [^foo] ref and no [^foo]: def: L-1 reported."""
    page = tmp_path / "wiki" / "page.md"
    page.parent.mkdir(parents=True)
    content = textwrap.dedent("""\
        ---
        format_version: 2
        updated: 2025-05-01
        ---

        # Page

        A claim about something[^foo].

        ---

        ## Timeline

        - 2025-05-01 - Page created.
    """)
    page.write_text(content)
    fm, body = _split(content)

    violations = run_all_checks(str(page), body, fm)

    l1 = [v for v in violations if v.get("rule") == "L-1"]
    assert len(l1) >= 1, f"Expected L-1 violation, got: {violations}"
    assert any("foo" in str(v.get("id", "")) for v in l1), (
        f"Expected violation to reference id 'foo', got: {l1}"
    )


# ---------------------------------------------------------------------------
# L-2: every [^id]: definition is referenced (warning severity)
# ---------------------------------------------------------------------------

def test_footnote_l2_def_without_ref_v2_warning(tmp_path):
    """v2 page with [^foo]: def but no body ref: L-2 reported as warning."""
    page = tmp_path / "wiki" / "page.md"
    page.parent.mkdir(parents=True)
    content = textwrap.dedent("""\
        ---
        format_version: 2
        updated: 2025-05-01
        ---

        # Page

        Plain prose with no footnote references here.

        ---

        ## Timeline

        - 2025-05-01 - Page created.

        [^foo]: [[raw/articles/foo]]
    """)
    page.write_text(content)
    fm, body = _split(content)

    violations = run_all_checks(str(page), body, fm)

    l2 = [v for v in violations if v.get("rule") == "L-2"]
    assert len(l2) >= 1, f"Expected L-2 violation, got: {violations}"
    assert l2[0].get("severity") == "warning", (
        f"L-2 should be severity=warning, got: {l2[0]}"
    )


# ---------------------------------------------------------------------------
# L-3: footnote IDs are unique within the page
# ---------------------------------------------------------------------------

def test_footnote_l3_duplicate_id_v2_reported(tmp_path):
    """v2 page with two [^foo]: defs: L-3 reported."""
    page = tmp_path / "wiki" / "page.md"
    page.parent.mkdir(parents=True)
    content = textwrap.dedent("""\
        ---
        format_version: 2
        updated: 2025-05-01
        ---

        # Page

        Claim one[^foo]. Claim two[^foo].

        ---

        ## Timeline

        - 2025-05-01 - Page created.

        [^foo]: [[raw/articles/foo]]
        [^foo]: [[raw/articles/other]]
    """)
    page.write_text(content)
    fm, body = _split(content)

    violations = run_all_checks(str(page), body, fm)

    l3 = [v for v in violations if v.get("rule") == "L-3"]
    assert len(l3) >= 1, f"Expected L-3 violation, got: {violations}"
    assert any("foo" in str(v.get("id", "")) for v in l3)


# ---------------------------------------------------------------------------
# L-4: footnote definitions sit after the timeline
# ---------------------------------------------------------------------------

def test_footnote_l4_placement_v2_reported(tmp_path):
    """v2 page with a [^foo]: def in the compiled-truth zone: L-4 reported."""
    page = tmp_path / "wiki" / "page.md"
    page.parent.mkdir(parents=True)
    content = textwrap.dedent("""\
        ---
        format_version: 2
        updated: 2025-05-01
        ---

        # Page

        Claim one[^foo].

        [^foo]: [[raw/articles/foo]]

        ---

        ## Timeline

        - 2025-05-01 - Page created.
    """)
    page.write_text(content)
    fm, body = _split(content)

    violations = run_all_checks(str(page), body, fm)

    l4 = [v for v in violations if v.get("rule") == "L-4"]
    assert len(l4) >= 1, f"Expected L-4 violation, got: {violations}"


def test_footnote_l4_placement_v2_pass_at_bottom(tmp_path):
    """v2 page with all defs after timeline: L-4 passes."""
    page = tmp_path / "wiki" / "page.md"
    page.parent.mkdir(parents=True)
    content = textwrap.dedent("""\
        ---
        format_version: 2
        updated: 2025-05-01
        ---

        # Page

        Claim one[^foo].

        ---

        ## Timeline

        - 2025-05-01 - Page created.

        [^foo]: [[raw/articles/foo]]
    """)
    page.write_text(content)
    fm, body = _split(content)

    violations = run_all_checks(str(page), body, fm)

    l4 = [v for v in violations if v.get("rule") == "L-4"]
    assert len(l4) == 0, f"Expected no L-4 violations, got: {l4}"


def test_footnote_l4_placement_def_between_timeline_bullets_reported(tmp_path):
    """v2 page with a [^foo]: def appearing BEFORE the last timeline bullet: L-4 fires.

    Regression for the off-by-N bug in `_last_timeline_line`: the previous
    implementation split on `\\n---\\s*\\n` and miscounted the lines consumed
    by the separator, so a def sandwiched between earlier and later timeline
    bullets was not flagged.
    """
    page = tmp_path / "wiki" / "page.md"
    page.parent.mkdir(parents=True)
    content = textwrap.dedent("""\
        ---
        format_version: 2
        updated: 2025-05-01
        ---

        # Page

        Prose[^foo].

        ---

        ## Timeline

        - 2025-01-01 - event one
        - 2025-02-01 - event two
        [^foo]: def appears between TL bullets and last TL bullet
        - 2025-03-01 - last event
    """)
    page.write_text(content)
    fm, body = _split(content)

    violations = run_all_checks(str(page), body, fm)

    l4 = [v for v in violations if v.get("rule") == "L-4"]
    assert len(l4) >= 1, (
        f"Expected L-4 violation for def before last timeline bullet, "
        f"got: {violations}"
    )
    assert l4[0].get("severity") == "error", (
        f"L-4 should be severity=error, got: {l4[0]}"
    )
    assert any("foo" in str(v.get("id", "")) for v in l4), (
        f"Expected violation to reference id 'foo', got: {l4}"
    )


# ---------------------------------------------------------------------------
# format_version dispatch tests
# ---------------------------------------------------------------------------

def test_format_version_legacy_no_new_rules(tmp_path):
    """Page without format_version: none of L-1..L-4 reported regardless of footnote content."""
    page = tmp_path / "wiki" / "page.md"
    page.parent.mkdir(parents=True)
    content = textwrap.dedent("""\
        ---
        updated: 2025-05-01
        ---

        # Page

        Unbalanced[^foo] claim. And another[^bar].

        [^foo]: [[raw/articles/foo]]
        [^foo]: duplicate id with no ref balance.
    """)
    page.write_text(content)
    fm, body = _split(content)

    violations = run_all_checks(str(page), body, fm)

    new_rule_codes = {"L-1", "L-2", "L-3", "L-4"}
    fired = [v for v in violations if v.get("rule") in new_rule_codes]
    assert fired == [], f"Legacy page should not trigger v2 rules, got: {fired}"


def test_format_version_string_2_treated_as_legacy(tmp_path):
    """format_version: '2' (string, not int): treated as legacy."""
    page = tmp_path / "wiki" / "page.md"
    page.parent.mkdir(parents=True)
    content = textwrap.dedent("""\
        ---
        format_version: "2"
        updated: 2025-05-01
        ---

        # Page

        Unbalanced[^foo] claim.
    """)
    page.write_text(content)
    fm, body = _split(content)
    # Sanity: PyYAML reads "2" as the string "2", not int 2.
    assert fm.get("format_version") == "2"
    assert isinstance(fm.get("format_version"), str)

    violations = run_all_checks(str(page), body, fm)

    new_rule_codes = {"L-1", "L-2", "L-3", "L-4"}
    fired = [v for v in violations if v.get("rule") in new_rule_codes]
    assert fired == [], f"String '2' should be legacy, got: {fired}"


def test_format_version_float_2_1_treated_as_legacy(tmp_path):
    """format_version: 2.1 (float): treated as legacy with a warning."""
    page = tmp_path / "wiki" / "page.md"
    page.parent.mkdir(parents=True)
    content = textwrap.dedent("""\
        ---
        format_version: 2.1
        updated: 2025-05-01
        ---

        # Page

        Unbalanced[^foo] claim.
    """)
    page.write_text(content)
    fm, body = _split(content)
    assert isinstance(fm.get("format_version"), float)

    violations = run_all_checks(str(page), body, fm)

    new_rule_codes = {"L-1", "L-2", "L-3", "L-4"}
    fired = [v for v in violations if v.get("rule") in new_rule_codes]
    assert fired == [], f"Float 2.1 should be legacy, got: {fired}"


def test_format_version_int_2_triggers_v2_rules(tmp_path):
    """format_version: 2 (bare int): v2 rules apply."""
    page = tmp_path / "wiki" / "page.md"
    page.parent.mkdir(parents=True)
    content = textwrap.dedent("""\
        ---
        format_version: 2
        updated: 2025-05-01
        ---

        # Page

        Unbalanced[^foo] claim.

        ---

        ## Timeline

        - 2025-05-01 - Page created.
    """)
    page.write_text(content)
    fm, body = _split(content)
    assert fm.get("format_version") == 2
    assert isinstance(fm.get("format_version"), int)

    violations = run_all_checks(str(page), body, fm)

    l1 = [v for v in violations if v.get("rule") == "L-1"]
    assert len(l1) >= 1, f"Int 2 should trigger v2 rules, got: {violations}"


def test_format_version_future_int_3_v2_rules_skipped(tmp_path):
    """format_version: 3 (future int): emits warning, no v2 rules applied."""
    page = tmp_path / "wiki" / "page.md"
    page.parent.mkdir(parents=True)
    content = textwrap.dedent("""\
        ---
        format_version: 3
        updated: 2025-05-01
        ---

        # Page

        Unbalanced[^foo] claim.
    """)
    page.write_text(content)
    fm, body = _split(content)
    assert fm.get("format_version") == 3

    violations = run_all_checks(str(page), body, fm)

    new_rule_codes = {"L-1", "L-2", "L-3", "L-4"}
    fired = [v for v in violations if v.get("rule") in new_rule_codes]
    assert fired == [], f"Future int 3 should not trigger v2 rules, got: {fired}"
