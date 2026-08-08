from itr1.rules.registry import registry_counts, rules, validate_registry


def test_registry_counts_match_cbdt_spec():
    counts = registry_counts()
    assert counts == {'A': 339, 'B': 9, 'D': 1, 'total': 349}


def test_registry_self_check_has_no_problems():
    assert validate_registry() == []


def test_rule_ids_are_unique():
    ids = [r.id for r in rules()]
    assert len(ids) == len(set(ids))
