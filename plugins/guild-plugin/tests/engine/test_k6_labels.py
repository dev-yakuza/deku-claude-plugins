"""K6 items 29 + 1 — the blind-label sample audit (replay/label_audit.py over word_app's 377 real AC lines) and the
calibration it led to.

* the r10 m5 paraphrases (16 — faithful / beyond / departs / 文字通り / 忠実 / 外れる / 食い違う / 충실 / 벗어난 / 확대 해석
  / 상통 / 취지에 부합 / 그대로 반영) now rate (cut or refuse) — they leaked before;
* their descriptive mirror stays untouched, and the bare domain word `mismatch` (3 real AC lines: account-anchor
  mismatch) is no longer fit language — only a mismatch WITH a source is;
* measured on the corpus (k6-notes): flagged 9 → 6 of 377 (2 of them true ratings), refused 6 → 3.
"""

import unittest

import _util  # noqa: F401

from workflows.dev import predict as PF
from workflows.dev.replay import label_audit as LA


class Calibration(unittest.TestCase):
    def test_r10_paraphrases_rate(self):
        for s in LA.EVALUATIVE:
            with self.subTest(label=s):
                self.assertTrue(PF.rates(s))
                self.assertNotEqual(PF.neutral_label(s), s)

    def test_descriptive_mirror_untouched(self):
        for s in LA.DESCRIPTIVE:
            with self.subTest(label=s):
                self.assertEqual(PF.neutral_label(s), s)

    def test_domain_mismatch_is_not_fit(self):
        for s in ("keep existing anchor-mismatch Crashlytics reason `SyncAutoAccountAnchorMismatch`",
                  "entry-time mismatch keeps the session alive (no cleanup)",
                  "업로드 첫 catch 에서 mismatch 를 먼저 판별한다"):
            with self.subTest(label=s):
                self.assertFalse(PF.rates(s))
        for s in ("Whole app (mismatch with the title)", "Login only (title mismatch)"):
            with self.subTest(label=s):
                self.assertTrue(PF.rates(s))

    def test_r9_labels_still_cut(self):
        import test_k5_r9 as R9
        for s in R9.M1LabelRule.EVALUATIVE:
            with self.subTest(label=s):
                self.assertTrue(PF.evaluative(s) or PF.rates(s))


if __name__ == "__main__":
    unittest.main()
