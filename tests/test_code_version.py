import unittest


class CodeVersionTests(unittest.TestCase):
    def test_code_version_unknown_current_and_older(self):
        from code_version import comparison
        latest={'fingerprint':'new','commit':'123'}
        self.assertEqual(comparison(None,latest)['status'],'unknown')
        self.assertEqual(comparison(latest,latest)['status'],'current')
        self.assertEqual(comparison(dict(fingerprint='old',commit='456'),latest)['status'],'older')
