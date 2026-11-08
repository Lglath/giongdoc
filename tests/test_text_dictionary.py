from giongdoc.core import Language
from giongdoc.text.dictionary import PronunciationDict

VI, EN = Language.VI, Language.EN


def test_default_vi_set():
    d = PronunciationDict.default()
    out = d.apply("AI trên TikTok, Facebook OK không? ai biết", VI)
    assert out == "ây ai trên tíc tóc, phây búc ô kê không? ai biết"
    # default set is Vietnamese only
    assert d.apply("AI on TikTok", EN) == "AI on TikTok"


def test_whole_word_only():
    d = PronunciationDict()
    d.add("AI", "ây ai")
    assert d.apply("AIDS và MAI và AI.", VI) == "AIDS và MAI và ây ai."


def test_case_rules():
    d = PronunciationDict()
    d.add("TikTok", "tíc tóc")           # mixed case -> case-insensitive
    d.add("AI", "ây ai")                 # acronym -> case-sensitive
    d.add("Nam", "NAM", case_sensitive=True)
    assert d.apply("tiktok TIKTOK ai AI nam Nam", VI) == "tíc tóc tíc tóc ai ây ai nam NAM"


def test_language_override_global():
    d = PronunciationDict()
    d.add("SQL", "es kiu eo")
    d.add("SQL", "ét quy eo", VI)
    assert d.apply("SQL", VI) == "ét quy eo"
    assert d.apply("SQL", EN) == "es kiu eo"
    assert d.lookup("SQL", VI) == "ét quy eo"


def test_longest_match_and_remove():
    d = PronunciationDict()
    d.add("Google", "gu gồ")
    d.add("Google Maps", "gu gồ máp")
    assert d.apply("Google Maps và Google", VI) == "gu gồ máp và gu gồ"
    assert d.remove("Google Maps")
    assert not d.remove("Google Maps")
    assert d.apply("Google Maps", VI) == "gu gồ Maps"


def test_save_load_roundtrip(tmp_path):
    d = PronunciationDict.default()
    d.add("Kpop", "kây póp", Language.KO)
    path = tmp_path / "dict.json"
    d.save(path)
    loaded = PronunciationDict.load(path)
    assert len(loaded) == len(d)
    assert loaded.apply("AI", VI) == "ây ai"
    assert loaded.lookup("kpop", Language.KO) == "kây póp"
    assert "Kpop" in loaded
    assert "ây ai" in path.read_text(encoding="utf-8")  # stored as readable UTF-8


def test_empty_dict_is_noop():
    assert PronunciationDict().apply("AI ok", VI) == "AI ok"
