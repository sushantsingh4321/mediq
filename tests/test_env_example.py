"""
Deployment step 7: .env.example lists EVERY setting the code reads, so nobody
deploying mediQ has to guess. This fails if someone adds os.getenv("NEW_THING")
without documenting it. Run from the mediq/ folder with:   pytest
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXAMPLE = (ROOT / ".env.example").read_text()
READ = re.compile(r"""os\.(?:getenv|environ\.get)\(\s*["']([A-Z0-9_]+)["']|os\.environ\[\s*["']([A-Z0-9_]+)["']\s*\]""")


def settings_the_code_reads() -> set[str]:
    names = set()
    for folder in ("backend", "api", "scripts", "migrations"):
        for f in (ROOT / folder).rglob("*.py"):
            if "__pycache__" not in f.parts:
                names |= {a or b for a, b in READ.findall(f.read_text())}
    return names


def test_every_setting_is_documented():
    documented = set(re.findall(r"\b([A-Z][A-Z0-9_]{2,})\b", EXAMPLE))      # as KEY= or mentioned in a comment
    assert settings_the_code_reads() - documented == set()


def test_the_vercel_essentials_are_marked():
    for name in ("DATABASE_URL", "SECRET_KEY", "DRY_RUN"):
        block = EXAMPLE[:EXAMPLE.index(f"\n{name}=")]
        assert "[Vercel:" in block[block.rfind("\n\n"):], name


def test_no_real_secrets_in_the_example():
    values = dict(re.findall(r"^([A-Z][A-Z0-9_]+)=(.*)$", EXAMPLE, re.M))
    assert values["SECRET_KEY"] == "" and values["ADMIN_PASSWORD"] == "" and values["DATABASE_URL"] == ""
    assert values["DRY_RUN"] == "true"
