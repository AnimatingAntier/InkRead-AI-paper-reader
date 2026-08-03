from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import document_store


class AnnotationStoreTests(unittest.TestCase):
    def test_annotations_are_sanitized_saved_and_loaded(self) -> None:
        payload = {
            "highlights": [
                {
                    "id": "highlight-1",
                    "page": 2,
                    "start": 4,
                    "end": 9,
                    "text": "selected paper text",
                    "color": "green",
                    "createdAt": 123,
                },
                {
                    "id": "highlight-2",
                    "page": -1,
                    "start": -5,
                    "end": -2,
                    "text": "invalid bounds become safe",
                    "color": "unknown",
                    "createdAt": 0,
                },
            ],
            "doodles": [
                {
                    "id": "stroke-1",
                    "page": 2,
                    "tool": "brush",
                    "color": "#9f3341",
                    "size": 0.004,
                    "opacity": 0.9,
                    "points": [{"x": 0.1, "y": 0.2}, {"x": 1.4, "y": -0.2}],
                    "createdAt": 456,
                }
            ],
            "comments": [
                {
                    "id": "comment-1",
                    "kind": "markdown",
                    "page": 1,
                    "start": 10,
                    "end": 20,
                    "text": "selected claim",
                    "content": "这是一条可编辑的旁注。",
                    "source": "ai",
                    "createdAt": 789,
                    "updatedAt": 800,
                },
                {
                    "id": "comment-2",
                    "kind": "unknown",
                    "page": -2,
                    "start": -5,
                    "end": -8,
                    "text": "bounds",
                    "content": "manual",
                    "source": "unknown",
                    "createdAt": 0,
                    "updatedAt": -1,
                },
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "annotations.json"
            with patch.object(document_store, "_annotation_path", return_value=path):
                saved = document_store.save_annotations("paper", payload)
                loaded = document_store.load_annotations("paper")

        self.assertEqual(saved, loaded)
        self.assertEqual(saved["highlights"][0]["color"], "green")
        self.assertEqual(saved["highlights"][1]["color"], "yellow")
        self.assertEqual(saved["highlights"][1]["page"], 1)
        self.assertEqual(saved["doodles"][0]["points"][1], {"x": 1.0, "y": 0.0})
        self.assertEqual(saved["comments"][0]["source"], "ai")
        self.assertEqual(saved["comments"][1]["kind"], "pdf")
        self.assertEqual(saved["comments"][1]["source"], "manual")
        self.assertEqual(saved["comments"][1]["page"], 1)
        self.assertGreater(saved["comments"][1]["end"], saved["comments"][1]["start"])

    def test_missing_annotation_file_returns_empty_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "annotations.json"
            with patch.object(document_store, "_annotation_path", return_value=path):
                self.assertEqual(
                    document_store.load_annotations("paper"),
                    {"highlights": [], "doodles": [], "comments": []},
                )


if __name__ == "__main__":
    unittest.main()
