"""GiongDoc text processing: normalization, detection, markup, segmentation."""
from giongdoc.text.detect import ScriptRun, detect_language, split_by_script
from giongdoc.text.dictionary import DictEntry, PronunciationDict
from giongdoc.text.markup import Span, parse_markup, strip_markup
from giongdoc.text.normalize import normalize, number_to_words
from giongdoc.text.pipeline import prepare
from giongdoc.text.segmenter import Clause, split_clauses

__all__ = [
    "prepare", "detect_language", "split_by_script", "ScriptRun", "PronunciationDict",
    "DictEntry", "parse_markup", "strip_markup", "Span", "normalize", "number_to_words",
    "split_clauses", "Clause",
]
