from giongdoc.text.segmenter import break_long, split_clauses, text_weight


def pairs(text, **kw):
    return [(c.text, c.pause_ms) for c in split_clauses(text, **kw)]


def test_pause_table():
    assert pairs("Một, hai; ba: bốn. Năm? Sáu! Bảy... Tám… Chín") == [
        ("Một,", 250), ("hai;", 400), ("ba:", 350), ("bốn.", 600), ("Năm?", 650),
        ("Sáu!", 650), ("Bảy...", 800), ("Tám…", 800), ("Chín", 0)]


def test_dash_pause_and_removal():
    assert pairs("Anh ấy — người tốt — đã đến.") == [("Anh ấy", 300), ("người tốt", 300), ("đã đến.", 600)]


def test_cjk_punctuation():
    assert pairs("你好，世界。真的吗？好！列表、项目；结束：") == [
        ("你好，", 250), ("世界。", 600), ("真的吗？", 650), ("好！", 650),
        ("列表、", 250), ("项目；", 400), ("结束：", 400)]


def test_line_and_paragraph_breaks():
    assert pairs("Dòng một\nDòng hai.\n\nĐoạn mới") == [("Dòng một", 700), ("Dòng hai.", 1100), ("Đoạn mới", 0)]


def test_leading_break_gives_empty_clause():
    assert pairs("\n\nXin chào") == [("", 1100), ("Xin chào", 0)]


def test_no_split_on_decimal_abbrev_time():
    assert pairs("Giá 3.5 triệu, lúc 14:30 ở TP.HCM.") == [("Giá 3.5 triệu,", 250), ("lúc 14:30 ở TP.HCM.", 600)]
    assert pairs("Dr. Smith and Mr. Lee met in the U.S. today.") == [
        ("Dr. Smith and Mr. Lee met in the U.S. today.", 600)]
    assert pairs("Có 1,000 người") == [("Có 1,000 người", 0)]


def test_closing_quotes_attach():
    assert pairs('Anh nói: "Đi thôi." Rồi đi.') == [("Anh nói:", 350), ('"Đi thôi."', 600), ("Rồi đi.", 600)]


def test_pause_scale():
    assert pairs("A, b.", pause_scale=2.0) == [("A,", 500), ("b.", 1200)]
    assert pairs("A, b.", pause_scale=0) == [("A,", 0), ("b.", 0)]


def test_punctuation_only_moves_pause_to_previous():
    assert pairs("Xin chào. ... !") == [("Xin chào.", 800)]


def test_long_clause_broken_at_natural_point():
    text = "Đây là một câu dài " + "không có dấu câu nào cả và nó cứ kéo dài mãi " * 8 + "đến hết"
    clauses = split_clauses(text)
    assert len(clauses) >= 2
    assert all(text_weight(c.text) <= 180 for c in clauses)
    assert all(c.pause_ms == 150 for c in clauses[:-1])
    # broken before a conjunction, never inside a word
    assert all(c.text.split()[0] in {"và", "mà", "nhưng", "Đây", "không", "nó"} for c in clauses)
    assert " ".join(c.text for c in clauses) == text.strip()


def test_long_cjk_clause():
    text = "这是一个很长的句子" * 12 + "。"
    clauses = split_clauses(text)
    assert len(clauses) == 2
    assert all(len(c.text) <= 61 for c in clauses)
    assert "".join(c.text for c in clauses) == text
    assert clauses[-1].pause_ms == 600


def test_break_long_short_text_unchanged():
    assert break_long("ngắn") == ["ngắn"]
