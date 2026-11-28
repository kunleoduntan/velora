"""docs/commands.md is generated from the real parser: nothing can be undocumented, no example can be wrong, and the page cannot drift."""
import argparse
import shlex
from pathlib import Path

import pytest

from velora import cli_docs
from velora.cli import _build_parser

ROOT = Path(__file__).resolve().parent.parent


def top_level():
    parser = _build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    helps = {c.dest: c.help for c in sub._choices_actions}
    return parser, sub, [n for n in sub.choices if helps.get(n) != argparse.SUPPRESS]


def test_every_argument_of_every_command_has_help_text():
    assert cli_docs.missing_help() == []                                                                      # `velora COMMAND --help` explains every option


def test_every_visible_command_has_a_one_line_help_in_the_command_list():
    parser, sub, names = top_level()
    helps = {c.dest: c.help for c in sub._choices_actions}
    assert [n for n in names if not helps.get(n)] == []                                                       # `velora --help` never shows a blank entry


def test_every_visible_command_is_grouped_and_explained():
    _, _, names = top_level()
    grouped = [n for _, g in cli_docs.GROUPS for n in g]
    assert sorted(set(names) - set(grouped)) == [] and sorted(set(grouped) - set(names)) == []                  # nothing undocumented, nothing documented that does not exist
    assert len(grouped) == len(set(grouped))
    assert [n for n in names if n not in cli_docs.NOTES] == [], "write what each command is for in velora/cli_docs.py NOTES"


def all_examples():
    return [(path, e) for path, (_, ex) in cli_docs.NOTES.items() for e in ex]


@pytest.mark.parametrize("path,example", all_examples())
def test_every_example_is_a_command_the_real_parser_accepts(path, example):
    parser = _build_parser()
    argv = shlex.split(example)
    assert argv[0] == "velora"
    try:
        parser.parse_args(argv[1:])
    except SystemExit as exit_:
        pytest.fail(f"example for `{path}` does not parse (exit {exit_.code}): {example}")


def test_every_example_belongs_to_the_command_it_is_listed_under():
    _, sub, _ = top_level()
    for path, example in all_examples():
        words = [w for w in shlex.split(example)[1:] if not w.startswith("-")]
        first = next(w for w in words if w in sub.choices)
        assert first == path.split()[0] or path.split()[0] in words, (path, example)


def test_the_ops_action_table_covers_every_ops_action_exactly():
    _, sub, _ = top_level()
    actions = next(a for a in sub.choices["ops"]._actions if a.dest == "action").choices
    documented = [row[0].split()[0] for row in cli_docs.OPS_ACTIONS]
    assert sorted(documented) == sorted(actions), set(documented) ^ set(actions)


def test_the_environment_table_lists_only_variables_the_code_really_reads():
    import re
    source = "\n".join(p.read_text() for d in ("velora", "velora_notify", "velora_search") for p in (ROOT / d).rglob("*.py") if p.name != "cli_docs.py")
    for names, _ in cli_docs.ENVIRONMENT:
        for name in re.findall(r"VELORA_[A-Z_]+", names):
            assert name in source, f"{name} is documented but nothing reads it"
    for important in ("VELORA_BACKUP_PASSWORD", "VELORA_MASTER_KEY", "VELORA_MAX_BODY_MB", "VELORA_WORKSPACE"):
        assert important in "".join(n for n, _ in cli_docs.ENVIRONMENT)


def test_the_committed_page_is_exactly_what_the_parser_generates():
    assert (ROOT / "docs" / "commands.md").read_text() == cli_docs.render()                                     # python -m velora.cli_docs docs/commands.md


def test_the_page_mentions_every_option_of_every_command():
    page = cli_docs.render()
    parser, sub, names = top_level()
    for n in names:
        for a in sub.choices[n]._actions:
            for flag in a.option_strings:
                if flag not in ("-h", "--help") and a.help != argparse.SUPPRESS:
                    assert f"`{flag}`" in page, (n, flag)
