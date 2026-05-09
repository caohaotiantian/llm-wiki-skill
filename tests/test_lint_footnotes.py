"""Tests for v2 footnote lint rules (L-1..L-4) + format_version dispatch
plus migration ops (M-1..M-5) on legacy pages."""

import os
import re
import sys
import textwrap

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "llm-wiki", "scripts"))

from frontmatter import parse as parse_fm
from lint_links import migrate_legacy_page, run_all_checks


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


# ---------------------------------------------------------------------------
# Migration tests (M-1..M-5) — Phase 2.
#
# `migrate_legacy_page(page_path, content) -> (new_content, MigrationReport)`
# performs the structural rewrite documented in design §2 D6 / §4.6 / §4.4.
# Each test below isolates a single migration concern so the AC-9 distinctness
# check (≥5 distinct migration test names) holds and so review can map each
# behavior back to one source of truth.
# ---------------------------------------------------------------------------


def _legacy_page(body_compiled: str, body_timeline: str = "", extra_fm: str = "") -> str:
    """Build a synthetic legacy page (no format_version) for migration tests."""
    fm = "updated: 2025-05-01\n"
    if extra_fm:
        fm += extra_fm
    return (
        "---\n"
        + fm
        + "---\n\n"
        + body_compiled
        + ("\n---\n\n" + body_timeline if body_timeline else "")
    )


# --- M-1: compiled-truth wikilinks → footnote refs/defs ---------------------


def test_migrate_m1_wikilink_to_footnote_basic(tmp_path):
    """One inline wikilink in compiled truth becomes [^foo] + def at file bottom."""
    page = tmp_path / "wiki" / "page.md"
    page.parent.mkdir(parents=True)
    content = _legacy_page(
        "# Page\n\nThe theory is well-established [[raw/articles/foo]].\n",
        "## Timeline\n\n- 2025-05-01 - created\n",
    )

    new_content, report = migrate_legacy_page(str(page), content)

    assert report.success is True, f"Expected migration success, got: {report}"
    fm, body = parse_fm(new_content)
    assert fm.get("format_version") == 2
    # Inline wikilink replaced by a footnote ref.
    assert "[^foo]" in body
    compiled_only = body.split("\n---\n", 1)[0]
    assert "[[raw/articles/foo]]" not in compiled_only, (
        "Wikilink should not survive in compiled-truth zone after migration"
    )
    # Definition block at file bottom carries the original wikilink.
    assert re.search(
        r"^\[\^foo\]:\s*\[\[raw/articles/foo\]\]\s*$", new_content, re.MULTILINE
    ), f"Expected `[^foo]: [[raw/articles/foo]]` def at bottom, got:\n{new_content}"


def test_migrate_m1_wikilink_to_footnote_collapse(tmp_path):
    """Two refs to the same wikilink target collapse to one footnote ID."""
    page = tmp_path / "wiki" / "page.md"
    page.parent.mkdir(parents=True)
    content = _legacy_page(
        "# Page\n\n"
        "First mention [[raw/articles/foo]] in this sentence.\n\n"
        "Second mention [[raw/articles/foo]] in another sentence.\n",
        "## Timeline\n\n- 2025-05-01 - created\n",
    )

    new_content, report = migrate_legacy_page(str(page), content)

    assert report.success is True
    # Both inline occurrences become [^foo].
    assert new_content.count("[^foo]") >= 3, (
        f"Expected at least two refs + one def for [^foo], got:\n{new_content}"
    )
    # Exactly one definition line.
    def_lines = re.findall(r"^\[\^foo\]:", new_content, re.MULTILINE)
    assert len(def_lines) == 1, (
        f"Expected exactly one [^foo]: def, got {len(def_lines)} in:\n{new_content}"
    )


def test_migrate_m1_wikilink_to_footnote_collision(tmp_path):
    """Two different targets with the same basename → -2 suffix in document order."""
    page = tmp_path / "wiki" / "page.md"
    page.parent.mkdir(parents=True)
    content = _legacy_page(
        "# Page\n\n"
        "Earlier reference [[raw/articles/foo]] in compiled truth.\n\n"
        "Later reference [[raw/notes/foo]] also in compiled truth.\n",
        "## Timeline\n\n- 2025-05-01 - created\n",
    )

    new_content, report = migrate_legacy_page(str(page), content)

    assert report.success is True
    _fm, body = parse_fm(new_content)
    compiled = body.split("\n---\n", 1)[0]
    # First occurrence keeps the bare ID; second gets -2.
    assert "[^foo]" in compiled
    assert "[^foo-2]" in compiled
    # Both definitions appear, each pointing at its original target.
    assert re.search(
        r"^\[\^foo\]:\s*\[\[raw/articles/foo\]\]", new_content, re.MULTILINE
    ), f"Expected [^foo] -> raw/articles/foo, got:\n{new_content}"
    assert re.search(
        r"^\[\^foo-2\]:\s*\[\[raw/notes/foo\]\]", new_content, re.MULTILINE
    ), f"Expected [^foo-2] -> raw/notes/foo, got:\n{new_content}"


def test_migrate_m1_relationships_skipped(tmp_path):
    """`## Relationships` bullets are NOT migrated (AC-11)."""
    page = tmp_path / "wiki" / "page.md"
    page.parent.mkdir(parents=True)
    content = _legacy_page(
        "# Page\n\n"
        "Inline prose mentions [[raw/articles/foo]] for context.\n\n"
        "## Relationships\n\n"
        "- [[raw/articles/bar]]\n"
        "- [[raw/articles/baz]]\n",
        "## Timeline\n\n- 2025-05-01 - created\n",
    )

    new_content, report = migrate_legacy_page(str(page), content)

    assert report.success is True
    # foo (inline prose) gets migrated.
    assert "[^foo]" in new_content
    # bar and baz (relationships bullets) are preserved verbatim.
    assert "- [[raw/articles/bar]]" in new_content, (
        f"Relationships bullet for bar should be untouched, got:\n{new_content}"
    )
    assert "- [[raw/articles/baz]]" in new_content, (
        f"Relationships bullet for baz should be untouched, got:\n{new_content}"
    )
    # No footnote refs/defs emitted for bar/baz.
    assert "[^bar]" not in new_content
    assert "[^baz]" not in new_content


def test_migrate_m1_fenced_code_skipped(tmp_path):
    """A wikilink inside a fenced code block is NOT migrated."""
    page = tmp_path / "wiki" / "page.md"
    page.parent.mkdir(parents=True)
    content = _legacy_page(
        "# Page\n\n"
        "Some prose with no wikilinks here.\n\n"
        "```\n"
        "Example: [[raw/articles/foo]]\n"
        "```\n",
        "## Timeline\n\n- 2025-05-01 - created\n",
    )

    new_content, report = migrate_legacy_page(str(page), content)

    assert report.success is True
    # The wikilink inside the fence survives byte-for-byte.
    assert "[[raw/articles/foo]]" in new_content
    # And no footnote ref/def for it.
    assert "[^foo]" not in new_content, (
        f"Fenced code wikilink should not be migrated, got:\n{new_content}"
    )


# --- M-2: ^[inferred] / ^[ambiguous] markers → frontmatter ------------------


def test_migrate_m2_confidence_to_frontmatter_basic(tmp_path):
    """`claim text. ^[inferred]` becomes claims_inferred: ['claim text.'] and marker is stripped."""
    page = tmp_path / "wiki" / "page.md"
    page.parent.mkdir(parents=True)
    content = _legacy_page(
        "# Page\n\nThe model has 175B parameters. ^[inferred]\n",
        "## Timeline\n\n- 2025-05-01 - created\n",
    )

    new_content, report = migrate_legacy_page(str(page), content)

    assert report.success is True
    fm, body = parse_fm(new_content)
    assert fm.get("claims_inferred") == ["The model has 175B parameters."], (
        f"Expected claims_inferred entry, got: {fm.get('claims_inferred')!r}"
    )
    # Inline marker stripped.
    assert "^[inferred]" not in body, (
        f"Inline marker should be stripped, got body:\n{body}"
    )


def test_migrate_m2_confidence_walk_back_bullet(tmp_path):
    """Marker on a bullet without prior `. ! ?`: capture from bullet's first non-whitespace char."""
    page = tmp_path / "wiki" / "page.md"
    page.parent.mkdir(parents=True)
    content = _legacy_page(
        "# Page\n\n- The deployment is regional ^[ambiguous]\n",
        "## Timeline\n\n- 2025-05-01 - created\n",
    )

    new_content, report = migrate_legacy_page(str(page), content)

    assert report.success is True
    fm, _ = parse_fm(new_content)
    captured = fm.get("claims_ambiguous") or []
    assert len(captured) == 1, f"Expected one entry, got: {captured!r}"
    # Captured text starts at bullet's first non-whitespace char ('T'), not the leading '-'.
    assert captured[0].startswith("The deployment is regional"), (
        f"Expected capture from bullet text start, got: {captured[0]!r}"
    )
    # Sanity: the leading hyphen / leading whitespace are NOT part of the entry.
    assert not captured[0].startswith("- "), (
        f"Capture should not include the bullet hyphen, got: {captured[0]!r}"
    )


def test_migrate_m2_confidence_walk_back_fail_question_mark(tmp_path):
    """Marker after 500+ chars of unbroken prose without boundary → entry is `?`."""
    page = tmp_path / "wiki" / "page.md"
    page.parent.mkdir(parents=True)
    # 600 chars of prose with no `. ! ?`, no bullet, no heading immediately before.
    blob = "x" * 600
    content = _legacy_page(
        "# Page\n\n" + blob + " ^[inferred]\n",
        "## Timeline\n\n- 2025-05-01 - created\n",
    )

    new_content, report = migrate_legacy_page(str(page), content)

    assert report.success is True
    fm, _ = parse_fm(new_content)
    captured = fm.get("claims_inferred") or []
    assert captured == ["?"], (
        f"Expected fallback `?` after 500+ char walk-back, got: {captured!r}"
    )


def test_migrate_m2_confidence_at_file_start_question_mark(tmp_path):
    """Marker at start of file (no prose before) → entry is `?`."""
    page = tmp_path / "wiki" / "page.md"
    page.parent.mkdir(parents=True)
    # No heading or prose before the marker — body opens straight with the marker.
    content = (
        "---\n"
        "updated: 2025-05-01\n"
        "---\n"
        "^[inferred]\n"
        "\n"
        "Some prose follows.\n"
        "\n"
        "---\n\n"
        "## Timeline\n\n"
        "- 2025-05-01 - created\n"
    )

    new_content, report = migrate_legacy_page(str(page), content)

    assert report.success is True
    fm, _ = parse_fm(new_content)
    captured = fm.get("claims_inferred") or []
    assert captured == ["?"], (
        f"Expected `?` for marker at body start, got: {captured!r}"
    )


# --- M-3: format_version added ---------------------------------------------


def test_migrate_m3_format_version_added(tmp_path):
    """A migrated legacy page gets `format_version: 2` (int) in frontmatter."""
    page = tmp_path / "wiki" / "page.md"
    page.parent.mkdir(parents=True)
    content = _legacy_page(
        "# Page\n\nA bare claim with no wikilinks or markers.\n",
        "## Timeline\n\n- 2025-05-01 - created\n",
    )

    new_content, report = migrate_legacy_page(str(page), content)

    assert report.success is True
    fm, _ = parse_fm(new_content)
    assert fm.get("format_version") == 2
    assert isinstance(fm.get("format_version"), int) and not isinstance(
        fm.get("format_version"), bool
    )
    assert report.format_version_after == 2


# --- M-4: idempotent on v2 pages -------------------------------------------


def test_migrate_m4_idempotent_v2_page_unchanged(tmp_path):
    """A v2 page passed through `migrate_legacy_page` is byte-equal pre/post."""
    page = tmp_path / "wiki" / "page.md"
    page.parent.mkdir(parents=True)
    content = textwrap.dedent("""\
        ---
        format_version: 2
        updated: 2025-05-01
        ---

        # Page

        Already migrated[^foo].

        ---

        ## Timeline

        - 2025-05-01 - created

        [^foo]: [[raw/articles/foo]]
    """)

    new_content, report = migrate_legacy_page(str(page), content)

    assert new_content == content, (
        "v2 page must be byte-equal pre/post (idempotency)"
    )
    assert report.skipped is True
    assert report.reason == "already_v2"


# --- M-5: pre-existing user footnotes get the `src-` prefix ----------------


def test_migrate_m5_pre_existing_footnote_src_prefix(tmp_path):
    """Page with hand-written `[^foo]` AND a `[[raw/articles/foo]]` wikilink:
    user's [^foo] preserved; migrator's derived ID is [^src-foo]."""
    page = tmp_path / "wiki" / "page.md"
    page.parent.mkdir(parents=True)
    content = _legacy_page(
        "# Page\n\n"
        "User's existing claim[^foo]. And then a wikilink [[raw/articles/foo]].\n\n"
        "[^foo]: existing user definition\n",
        "## Timeline\n\n- 2025-05-01 - created\n",
    )

    new_content, report = migrate_legacy_page(str(page), content)

    assert report.success is True
    # User's footnote ref preserved.
    assert "claim[^foo]" in new_content, (
        f"User's [^foo] reference must survive, got:\n{new_content}"
    )
    # User's footnote definition preserved verbatim.
    assert "[^foo]: existing user definition" in new_content, (
        f"User's [^foo]: def must survive byte-for-byte, got:\n{new_content}"
    )
    # Migrator-derived ID for the wikilink uses src- prefix.
    assert "[^src-foo]" in new_content, (
        f"Migrator-derived ID should be [^src-foo], got:\n{new_content}"
    )
    assert re.search(
        r"^\[\^src-foo\]:\s*\[\[raw/articles/foo\]\]", new_content, re.MULTILINE
    ), f"Expected `[^src-foo]: [[raw/articles/foo]]` def, got:\n{new_content}"
    # The wikilink in compiled truth has been replaced.
    _fm2, body2 = parse_fm(new_content)
    compiled = body2.split("\n---\n", 1)[0]
    assert "[[raw/articles/foo]]" not in compiled


def test_migrate_m5_pre_existing_footnote_byte_equal(tmp_path):
    """R-9: user's [^foo] ref AND def strings are byte-equal preserved pre/post."""
    page = tmp_path / "wiki" / "page.md"
    page.parent.mkdir(parents=True)
    user_ref = "user-authored claim[^foo]"
    user_def = "[^foo]: user's hand-written definition with [[some/wikilink]] inside"
    content = _legacy_page(
        "# Page\n\n"
        + user_ref
        + ". Plus a separate inline [[raw/articles/bar]] wikilink.\n\n"
        + user_def
        + "\n",
        "## Timeline\n\n- 2025-05-01 - created\n",
    )

    new_content, report = migrate_legacy_page(str(page), content)

    assert report.success is True
    # The user's exact ref string survives.
    assert user_ref in new_content, (
        f"User's footnote ref must be byte-equal, got:\n{new_content}"
    )
    # The user's exact def string survives.
    assert user_def in new_content, (
        f"User's footnote def must be byte-equal, got:\n{new_content}"
    )
    # Migrator-derived ID for the unrelated wikilink uses src- prefix
    # (because the page already contains user footnotes).
    assert "[^src-bar]" in new_content, (
        f"Expected [^src-bar] for migrator-derived id, got:\n{new_content}"
    )
