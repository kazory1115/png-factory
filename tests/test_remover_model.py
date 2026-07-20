import unittest
from unittest.mock import patch

from app import remover


class ModelSessionTests(unittest.TestCase):
    def tearDown(self) -> None:
        remover._MODEL_SESSION = None

    def test_prepare_model_reuses_loaded_session(self) -> None:
        session = object()
        with patch.object(remover, "rembg_new_session", return_value=session) as loader:
            self.assertIs(remover.prepare_model(), session)
            self.assertIs(remover.prepare_model(), session)
        loader.assert_called_once_with()

    def test_prepare_model_reports_missing_engine(self) -> None:
        with patch.object(remover, "rembg_new_session", None):
            with self.assertRaisesRegex(RuntimeError, "去背引擎載入失敗"):
                remover.prepare_model()


if __name__ == "__main__":
    unittest.main()
