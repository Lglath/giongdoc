from giongdoc.core import Language, ProsodySettings, Segment
from giongdoc.text import PronunciationDict, detect_language, prepare

VI, EN, KO, ZH = Language.VI, Language.EN, Language.KO, Language.ZH


def simple(segs):
    return [(s.text, s.language, s.pause_after_ms) for s in segs]


def test_public_api():
    assert callable(prepare) and callable(detect_language) and PronunciationDict


def test_basic_vietnamese():
    segs = prepare("Xin chào! Hôm nay là 08/11/2026, giá 1.500.000đ.")
    assert all(isinstance(s, Segment) for s in segs)
    assert simple(segs) == [
        ("Xin chào!", VI, 650),
        ("Hôm nay là ngày tám tháng mười một năm hai nghìn không trăm hai mươi sáu,", VI, 250),
        ("giá một triệu năm trăm nghìn đồng.", VI, 600),
    ]


def test_auto_detect_and_default_language():
    assert prepare("Hello world.")[0].language == EN
    assert prepare("Hello world.", default_language=VI)[0].language == VI


def test_mixed_language_sentence():
    segs = prepare("Tôi nói 안녕하세요 với bạn.")
    assert simple(segs) == [("Tôi nói", VI, 0), ("안녕하세요", KO, 0), ("với bạn.", VI, 600)]


def test_explicit_pause():
    segs = prepare("Một. [pause 2000] Hai.")
    assert simple(segs) == [("Một.", VI, 2000), ("Hai.", VI, 600)]
    segs = prepare("[pause 500]Xin chào")
    assert simple(segs) == [("", VI, 500), ("Xin chào", VI, 0)]
    segs = prepare("A [pause 300][ngat 200] B", default_language=EN)
    assert segs[0].pause_after_ms == 500


def test_explicit_pause_not_scaled_but_punctuation_is():
    segs = prepare("Một, hai. [pause 100] Ba", settings=ProsodySettings(pause_scale=2.0))
    assert [s.pause_after_ms for s in segs] == [500, 100, 0]


def test_paragraph_pause():
    segs = prepare("Đoạn một.\n\nĐoạn hai.\nDòng ba")
    assert [s.pause_after_ms for s in segs] == [1100, 700, 0]


def test_voice_rate_emphasis_lang():
    settings = ProsodySettings(rate=1.2, pitch=1.0)
    segs = prepare("[voice:edge:vi-VN-NamMinhNeural][rate 0.5]Chậm *lắm*[/rate][/voice] [lang:en]OK then.[/lang]",
                   settings=settings)
    assert segs[0].voice_id == "edge:vi-VN-NamMinhNeural"
    assert abs(segs[0].prosody.rate - 0.6) < 1e-9 and segs[0].prosody.pitch == 1.0
    assert segs[1].text == "lắm" and segs[1].emphasis
    assert segs[-1].language == EN and segs[-1].text == "OK then."  # dictionary is vi-only
    assert segs[-1].prosody is None and segs[-1].voice_id is None


def test_dictionary_default_and_disabled():
    assert prepare("Tôi dùng AI.")[0].text == "Tôi dùng ây ai."
    assert prepare("Tôi dùng AI.", dictionary=PronunciationDict())[0].text == "Tôi dùng AI."
    d = PronunciationDict()
    d.add("GiongDoc", "giọng đọc")
    assert prepare("Ứng dụng GiongDoc.", dictionary=d)[0].text == "Ứng dụng giọng đọc."


def test_empty_and_punctuation_only():
    assert prepare("") == []
    assert prepare("   \n\n  ") == []
    assert simple(prepare("Xin chào. ... 😀")) == [("Xin chào.", VI, 800)]


def test_korean_and_chinese_documents():
    ko = prepare("제 이름은 김민수입니다. 만나서 반갑습니다!")
    assert simple(ko) == [("제 이름은 김민수입니다.", KO, 600), ("만나서 반갑습니다!", KO, 650)]
    zh = prepare("你好，我是Nam。今天很好！")
    assert simple(zh) == [("你好，", ZH, 250), ("我是Nam。", ZH, 600), ("今天很好！", ZH, 650)]


def test_deterministic():
    text = "Giá 50% [pause 300] *rất* tốt, v.v. Xem https://a.b. Hết."
    assert simple(prepare(text)) == simple(prepare(text))
