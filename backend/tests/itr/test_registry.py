from itr.rules.registry import registry_counts, rules, validate_registry


def test_registry_counts_match_cbdt_spec():
    counts = registry_counts()
    # A-107 (IFSC/RBI-database verification) was removed -- this product no
    # longer verifies IFSCs against an external directory.
    # B-1 (Aadhaar-PAN linkage) was removed -- it asserted
    # personalInfo.aadhaarLinkedToPan, a field with no input anywhere in the
    # UI, so it fired as an unconditional advisory for every return rather
    # than reflecting an actual checked fact.
    assert counts == {'A': 338, 'B': 8, 'D': 1, 'total': 347}


def test_registry_self_check_has_no_problems():
    assert validate_registry() == []


def test_rule_ids_are_unique():
    ids = [r.id for r in rules()]
    assert len(ids) == len(set(ids))
