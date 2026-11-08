from giongdoc.core import Language
from giongdoc.text.markup import parse_language, parse_markup, strip_markup


def test_plain_text_single_span():
    spans = parse_markup("Xin chào")
    assert len(spans) == 1 and spans[0].text == "Xin chào" and not spans[0].is_pause


def test_pause_variants():
    spans = parse_markup("A[pause 800]B[ngat 300]C[ngắt 200ms]")
    assert [s.pause_ms for s in spans if s.is_pause] == [800, 300, 200]
    assert [s.text for s in spans if not s.is_pause] == ["A", "B", "C"]


def test_voice_lang_rate_nesting():
    spans = parse_markup("a[voice:edge:vi-VN-NamMinhNeural]b[lang:ko]c[/lang][rate 0.8]d[/rate][/voice]e")
    by_text = {s.text: s for s in spans}
    assert by_text["a"].voice_id is None
    assert by_text["b"].voice_id == "edge:vi-VN-NamMinhNeural"
    assert by_text["c"].language == Language.KO and by_text["c"].voice_id == "edge:vi-VN-NamMinhNeural"
    assert by_text["d"].rate == 0.8 and by_text["d"].language is None
    assert by_text["e"].voice_id is None and by_text["e"].rate is None


def test_emphasis():
    spans = parse_markup("Đây là *quan trọng* nhé, 2*3 không")
    emph = [s for s in spans if s.emphasis]
    assert [s.text for s in emph] == ["quan trọng"]
    assert "2*3" in "".join(s.text for s in spans)


def test_unclosed_and_stray_tags():
    spans = parse_markup("[lang:en]hello[/voice] world")
    assert all(s.language == Language.EN for s in spans)
    assert "".join(s.text for s in spans) == "hello world"


def test_unknown_brackets_kept():
    assert strip_markup("Xem [1] và [ghi chú]") == "Xem [1] và [ghi chú]"


def test_strip_markup():
    assert strip_markup("[voice:x]Chào[/voice] [pause 500]*bạn*") == "Chào  bạn"


def test_parse_language():
    assert parse_language("vi-VN") == Language.VI
    assert parse_language("zh_CN") == Language.ZH
    assert parse_language("kr") == Language.KO
    assert parse_language("fr") is None
