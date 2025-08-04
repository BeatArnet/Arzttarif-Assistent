from synonyms.scorer import score_synonym
def test_score_synonym_exact_and_normalized():
    assert score_synonym("foo", "foo") == 1.0
    assert score_synonym(" Foo ", "foo") == 1.0


def test_score_synonym_partial():
    score = score_synonym("foobar", "foo")
    assert 0 < score < 1.0
