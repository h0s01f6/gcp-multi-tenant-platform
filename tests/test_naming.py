"""K18 – service-account length budget boundary tests."""
import pytest

from tools.registry.naming import derived_names, validate_names

CASES = [
    ("longest valid: migration SA = 30", "abcdefghij", "abcdefghijk", "prd", True),
    ("customer 11 chars -> 31", "abcdefghijk", "abcdefghijk", "prd", False),
    ("product 12 chars -> 31", "abcdefghij", "abcdefghijkl", "prd", False),
    ("shortest valid", "abc", "hr", "dev", True),
    ("customer too short", "ab", "payroll", "dev", False),
    ("hyphen in customer", "ab-c", "payroll", "dev", False),
    ("hyphen in product", "abc", "pay-roll", "dev", False),
    ("uppercase", "ABC", "payroll", "dev", False),
    ("leading digit", "1abc", "payroll", "dev", False),
    ("unknown env", "abc", "payroll", "qa", False),
]


@pytest.mark.parametrize("desc,c,p,e,ok", CASES, ids=[c[0] for c in CASES])
def test_boundaries(desc, c, p, e, ok):
    assert (validate_names(c, p, e) == []) is ok


def test_longest_ids_exact_lengths():
    n = derived_names("abcdefghij", "abcdefghijk", "prd")
    assert [len(x) for x in n["sa_ids"]] == [26, 29, 30]
    assert max(len(r) for r in n["mysql_roles"]) == 28


def test_slugs_without_hyphens_cannot_collide():
    # Hyphen-free slugs make '<cust>-<product>-<env>' unambiguous: different pairs never yield the same ID.
    pairs = [("abc", "payroll"), ("abcp", "ayroll"), ("ab0", "cpayroll")]
    ids = {derived_names(c, p, "prd")["sa_ids"][0] for c, p in pairs}
    assert len(ids) == len(pairs)
