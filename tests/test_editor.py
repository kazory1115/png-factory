import unittest
import importlib.util

import numpy as np
from PIL import Image

from app.editor import CutoutEditor, adaptive_edge_alpha


def make_editor(width: int = 160, height: int = 120) -> CutoutEditor:
    rgb = np.full((height, width, 3), 235, dtype=np.uint8)
    rgb[25:95, 45:115] = (180, 45, 35)
    alpha = np.zeros((height, width), dtype=np.uint8)
    alpha[25:95, 45:115] = 255
    source = Image.fromarray(
        np.dstack((rgb, np.full((height, width), 255, dtype=np.uint8))), "RGBA"
    )
    cutout = Image.fromarray(np.dstack((rgb, alpha)), "RGBA")
    return CutoutEditor(source, cutout)


class CutoutEditorTests(unittest.TestCase):
    def test_adaptive_edge_alpha_keeps_solid_regions_and_narrow_transition(self) -> None:
        rgb = np.full((64, 64, 3), 245, dtype=np.uint8)
        rgb[:, 32:] = (230, 165, 25)
        foreground = np.zeros((64, 64), dtype=np.uint8)
        foreground[:, 32:] = 255
        prior = foreground.copy()

        alpha = adaptive_edge_alpha(rgb, foreground, prior)

        self.assertTrue(np.all(alpha[:, :27] == 0))
        self.assertTrue(np.all(alpha[:, 37:] == 255))
        transition = (alpha > 0) & (alpha < 255)
        self.assertFalse(np.any(transition[:, :27]))
        self.assertFalse(np.any(transition[:, 37:]))

    def test_clone_is_independent_and_keeps_history(self) -> None:
        editor = make_editor()
        editor.begin_stroke()
        editor.paint(40, 60, 8, "restore")

        clone = editor.clone()
        clone.paint(10, 10, 5, "restore", 1.0)

        self.assertNotEqual(np.asarray(clone.alpha)[10, 10], np.asarray(editor.alpha)[10, 10])
        self.assertTrue(clone.undo())

    def test_smart_refine_uses_edited_mask_without_preserving_guidance(self) -> None:
        if importlib.util.find_spec("cv2") is None:
            self.skipTest("OpenCV is not installed")
        editor = make_editor()
        editor.begin_stroke()
        editor.paint(40, 60, 6, "restore", 1.0)
        editor.paint(130, 60, 6, "erase", 1.0)

        editor.smart_refine(iterations=1, max_working_dimension=96)
        alpha = np.asarray(editor.alpha)

        self.assertEqual(alpha.shape, (120, 160))
        self.assertEqual(editor.alpha.getextrema(), (0, 255))
        self.assertFalse(editor.has_guidance())
        self.assertTrue(editor.undo())

    def test_smart_refine_requires_guidance(self) -> None:
        with self.assertRaisesRegex(ValueError, "請先用"):
            make_editor().smart_refine(iterations=1)


if __name__ == "__main__":
    unittest.main()
