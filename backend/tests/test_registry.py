from itr.rules.registry import registry_counts, rules, validate_registry


def test_registry_counts_match_cbdt_spec():
    counts = registry_counts()
    # A-107 (IFSC/RBI-database verification) was removed -- this product no
    # longer verifies IFSCs against an external directory.
    assert counts == {'A': 338, 'B': 9, 'D': 1, 'total': 348}


def test_registry_self_check_has_no_problems():
    assert validate_registry() == []


def test_rule_ids_are_unique():
    ids = [r.id for r in rules()]
    assert len(ids) == len(set(ids))
