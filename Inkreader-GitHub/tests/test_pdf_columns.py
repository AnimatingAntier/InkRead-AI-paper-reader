from __future__ import annotations

import unittest

from document_store import _annotate_pdf_columns


def make_word(text: str, x: float, y: float, block: int, word: int) -> dict:
    return {
        "text": text,
        "x": x,
        "y": y,
        "w": 28,
        "h": 10,
        "block": block,
        "line": word // 5,
        "word": word,
    }


class PdfColumnTests(unittest.TestCase):
    def test_two_column_words_are_grouped_by_column(self):
        words = []
        for index in range(20):
            words.append(make_word(f"L{index}", 50 + (index % 5) * 32, 80 + (index // 5) * 14, 1, index))
            words.append(make_word(f"R{index}", 330 + (index % 5) * 32, 80 + (index // 5) * 14, 2, index))

        ordered, split = _annotate_pdf_columns(words, 600)

        self.assertIsNotNone(split)
        self.assertTrue(all(word["column"] == "left" for word in ordered[:20]))
        self.assertTrue(all(word["column"] == "right" for word in ordered[20:]))

    def test_single_column_page_remains_shared(self):
        words = [
            make_word(f"W{index}", 80 + (index % 8) * 45, 60 + (index // 8) * 14, 1, index)
            for index in range(32)
        ]
        for word in words:
            word["w"] = 40

        ordered, split = _annotate_pdf_columns(words, 500)

        self.assertIsNone(split)
        self.assertTrue(all(word["column"] == "shared" for word in ordered))


if __name__ == "__main__":
    unittest.main()
