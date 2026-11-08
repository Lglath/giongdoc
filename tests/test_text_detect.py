from giongdoc.core import Language
from giongdoc.text.detect import detect_language, split_by_script

VI, EN, KO, ZH = Language.VI, Language.EN, Language.KO, Language.ZH


def test_detect_basic():
    assert detect_language("Xin chào các bạn, hôm nay trời đẹp quá") == VI
    assert detect_language("Hello there, how are you today?") == EN
    assert detect_language("안녕하세요. 만나서 반갑습니다") == KO
    assert detect_language("你好，世界。今天天气很好") == ZH


def test_detect_edge_cases():
    assert detect_language("") == VI
    assert detect_language("12345 !!!", default=EN) == EN
    assert detect_language("I had a café au lait this morning with friends") == EN
    assert detect_language("Tôi nói 안녕하세요 với bạn của tôi hôm qua") == VI
    # decomposed (NFD) Vietnamese still detected
    assert detect_language("Việt Nam đẹp") == VI


def test_split_vi_with_korean():
    runs = split_by_script("Tôi nói 안녕하세요 với bạn.", VI)
    assert [r.language for r in runs] == [VI, KO, VI]
    assert "".join(r.text for r in runs) == "Tôi nói 안녕하세요 với bạn."
    assert runs[1].text.strip() == "안녕하세요"


def test_split_punctuation_stays_with_previous_run():
    runs = split_by_script("안녕하세요. Xin chào", VI)
    assert runs[0] == ("안녕하세요.", KO)
    assert runs[1].language == VI


def test_split_digits_go_to_following_run():
    runs = split_by_script("Tôi gặp 김민수 2 lần", VI)
    assert runs[-1].language == VI and "2" in runs[-1].text


def test_split_chinese_with_latin_name():
    runs = split_by_script("Rồi 你好，我是Nam。 Xong", VI)
    assert [r.language for r in runs] == [VI, ZH, VI]
    assert runs[1].text.strip() == "你好，我是Nam。"


def test_split_english_default_switches_on_vietnamese_sentence():
    runs = split_by_script("I like it. Phở bò rất ngon. Bye", EN)
    assert [r.language for r in runs] == [EN, VI, EN]


def test_split_neutral_only():
    assert split_by_script("123 !", KO) == [("123 !", KO)]
    assert split_by_script("", KO) == []
