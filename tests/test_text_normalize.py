import pytest

from giongdoc.core import Language
from giongdoc.text.normalize import (clean_text, en_number, en_ordinal, en_year, normalize,
                                     number_to_words, vi_number, vi_numstr)

VI, EN = Language.VI, Language.EN


@pytest.mark.parametrize("n, words", [
    (0, "không"), (5, "năm"), (10, "mười"), (11, "mười một"), (15, "mười lăm"),
    (21, "hai mươi mốt"), (24, "hai mươi tư"), (25, "hai mươi lăm"), (30, "ba mươi"),
    (100, "một trăm"), (105, "một trăm linh năm"), (110, "một trăm mười"),
    (1000, "một nghìn"), (1005, "một nghìn không trăm linh năm"),
    (2026, "hai nghìn không trăm hai mươi sáu"), (1_500_000, "một triệu năm trăm nghìn"),
    (1_000_000_000, "một tỷ"), (5_000_000_000_000, "năm nghìn tỷ"), (-3, "âm ba"),
])
def test_vi_number(n, words):
    assert vi_number(n) == words


def test_vi_numstr_formats():
    assert vi_numstr("1.500.000") == "một triệu năm trăm nghìn"
    assert vi_numstr("3,5") == "ba phẩy năm"
    assert vi_numstr("0,05") == "không phẩy không năm"
    assert vi_numstr("0912345678").startswith("không chín một hai")


def test_en_numbers():
    assert en_number(21) == "twenty-one"
    assert en_number(105) == "one hundred five"
    assert en_number(1_500_000) == "one million five hundred thousand"
    assert en_year(1999) == "nineteen ninety-nine"
    assert en_year(2026) == "twenty twenty-six"
    assert en_year(2005) == "two thousand five"
    assert en_ordinal(21) == "twenty-first"
    assert en_ordinal(40) == "fortieth"
    assert number_to_words("3.14", EN) == "three point one four"
    assert number_to_words(-21, VI) == "âm hai mươi mốt"


def test_vi_date_time():
    assert normalize("08/11/2026", VI) == \
        "ngày tám tháng mười một năm hai nghìn không trăm hai mươi sáu"
    assert normalize("Ngày 15/3 đi", VI) == "Ngày mười lăm tháng ba đi"
    assert normalize("tháng 4/2025", VI) == "tháng tư năm hai nghìn không trăm hai mươi lăm"
    assert normalize("lúc 14:30", VI) == "lúc mười bốn giờ ba mươi phút"
    assert normalize("lúc 8h", VI) == "lúc tám giờ"
    assert normalize("lúc 8h05", VI) == "lúc tám giờ năm phút"


def test_vi_money_percent_units():
    assert normalize("1.500.000đ", VI) == "một triệu năm trăm nghìn đồng"
    assert normalize("200 VND", VI) == "hai trăm đồng"
    assert normalize("$5", VI) == "năm đô la"
    assert normalize("50%", VI) == "năm mươi phần trăm"
    assert normalize("3,5%", VI) == "ba phẩy năm phần trăm"
    assert normalize("5km", VI) == "năm ki lô mét"
    assert normalize("2 kg", VI) == "hai ki lô gam"
    assert normalize("-5°C", VI) == "âm năm độ C"
    assert normalize("50k", VI) == "năm mươi nghìn"
    assert normalize("100 ₩", VI) == "một trăm uôn"


def test_vi_abbreviations_and_misc():
    assert normalize("Ở TP.HCM", VI) == "Ở thành phố Hồ Chí Minh"
    assert normalize("táo, cam, v.v.", VI) == "táo, cam, vân vân."
    assert normalize("UBND xã", VI) == "ủy ban nhân dân xã"
    assert normalize("từ 5-10 người", VI) == "từ năm đến mười người"
    assert normalize("thứ 4", VI) == "thứ tư"
    assert normalize("hạng 1", VI) == "hạng nhất"
    assert normalize("COVID-19", VI) == "COVID mười chín"
    assert normalize("1/2 số người", VI) == "một phần hai số người"


def test_english_normalization():
    out = normalize("Mr. Smith paid $5.50 on 11/08/2026 at 3:05 pm for 12% more.", EN)
    assert out == ("Mister Smith paid five dollars and fifty cents on November eighth, "
                   "twenty twenty-six at three oh five p m for twelve percent more.")
    assert normalize("1,500,000 items, 1 km", EN) == "one million five hundred thousand items, one kilometer"
    assert normalize("in 1999", EN) == "in nineteen ninety-nine"
    assert normalize("the 21st time", EN) == "the twenty-first time"


def test_cjk_keeps_digits():
    assert normalize("가격은 3,000원입니다", Language.KO) == "가격은 3,000원입니다"
    assert normalize("我有3个苹果", Language.ZH) == "我有3个苹果"


def test_clean_text():
    assert clean_text("Xin   chào 😀  bạn") == "Xin chào bạn"
    assert clean_text("Xem https://example.com/a?b=1. Hết") == "Xem. Hết"
    assert clean_text("a\r\n\n\n\nb") == "a\n\nb"
    assert clean_text("- mục một\n• mục hai") == "mục một\nmục hai"
    assert clean_text("１２３") == "123"
    # NFC: decomposed input becomes precomposed
    assert clean_text("Việt") == "Việt"


def test_email():
    assert normalize("ab@gmail.com", VI) == "ab a còng gmail chấm com"
    assert normalize("ab@gmail.com", EN) == "ab at gmail dot com"


def test_ranges_and_per_unit():
    assert normalize("8h-9h30", VI) == "tám giờ đến chín giờ ba mươi phút"
    assert normalize("10:00-11:30", VI) == "mười giờ đến mười một giờ ba mươi phút"
    assert normalize("3.000.000 VNĐ/tháng", VI) == "ba triệu đồng trên tháng"
    assert normalize("120 km/h", VI) == "một trăm hai mươi ki lô mét trên giờ"
    assert normalize("và/hoặc", VI) == "và/hoặc"
    assert normalize("$5/hour", EN) == "five dollars per hour"
