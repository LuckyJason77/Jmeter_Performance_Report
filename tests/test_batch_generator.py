import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import batch_generator


class GenerateIndexTests(unittest.TestCase):
    def test_generate_index_writes_escaped_report_entry(self):
        reports = [("demo <load>&.jtl", "demo report.html", 12)]

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(batch_generator, "OUTPUT_DIR", Path(temp_dir)):
                batch_generator.generate_index(reports)

            index_html = (Path(temp_dir) / "index.html").read_text(encoding="utf-8")

        self.assertIn("demo &lt;load&gt;&amp;.jtl", index_html)
        self.assertIn('href="demo%20report.html"', index_html)


if __name__ == "__main__":
    unittest.main()
