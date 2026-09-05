"""Regression tests for recognition without a game window or network calls."""
import copy
import json
from pathlib import Path
import queue
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import numpy as np

from wingmen.star_citizen_services.functions.mining_services import mining_manager as mining


class SignatureRecognitionTests(unittest.TestCase):
    def setUp(self):
        self.manager = object.__new__(mining.MiningManager)
        self.manager.signature_observer_config = copy.deepcopy(mining.SIGNATURE_OBSERVER_DEFAULTS)
        self.manager._signature_debug = Mock()
        self.manager.signature_last_ocr_value_support = {}
        self.manager.signature_vision_cache = {}
        self.manager.signature_vision_recent_crops = []
        self.manager.signature_vision_queued_hashes = set()
        self.manager.signature_vision_queued_at_by_hash = {}
        self.manager.signature_observer_lock = threading.RLock()
        self.crop = np.zeros((36, 120, 3), dtype=np.uint8)

    def test_exact_hash_distinguishes_small_pixel_changes(self):
        changed = self.crop.copy()
        changed[12, 45] = 1
        self.assertNotEqual(self.manager._signature_crop_hash(self.crop), self.manager._signature_crop_hash(changed))
        self.assertEqual(self.manager._signature_crop_hash(self.crop), self.manager._signature_crop_hash(self.crop.copy()))

    def test_ocr_stops_after_independent_variants_agree(self):
        variants = [(name, self.crop) for name in ("gray", "light_text", "otsu")]
        with patch.object(mining.pytesseract, "image_to_string", return_value="21,350\n") as ocr:
            results = self.manager._run_signature_ocr_variants(variants, [7, 8, 13], 2)
        self.assertEqual(ocr.call_count, 2)
        self.assertEqual([r["value"] for r in results], [21350, 21350])
        self.assertEqual([r["variant"] for r in results], ["gray", "light_text"])

    def test_ocr_budget_limits_even_first_timeout(self):
        self.manager.signature_observer_config["ocr_tick_budget_seconds"] = 0.75
        with patch.object(mining.time, "perf_counter", side_effect=[0, 0.1, 0.8]), patch.object(
            mining.pytesseract, "image_to_string", side_effect=RuntimeError("timeout")
        ) as ocr:
            result = self.manager._run_signature_ocr_variants([("gray", self.crop)], [7, 8], 2)
        self.assertEqual(result, [])
        self.assertEqual(ocr.call_count, 1)
        self.assertAlmostEqual(ocr.call_args.kwargs["timeout"], 0.65)

    def test_ocr_rejects_multiple_numbers_and_short_reads(self):
        for text in ("21350\n500", "21350 500", "abc21350", "350", "21,35"):
            with self.subTest(text=text), patch.object(mining.pytesseract, "image_to_string", return_value=text):
                self.assertEqual(self.manager._run_signature_ocr_variants([("gray", self.crop)], [7], 2), [])

    def test_tied_ocr_results_are_uncertain(self):
        results = [dict(value=value, digits=str(value), variant=variant, psm=7)
                   for value, variant in ((21350, "gray"), (21850, "light_text"))]
        self.assertIsNone(self.manager._select_signature_ocr_result(results))
        self.manager._log_signature_ocr_candidates(results, None, "test")

    def test_one_preprocessing_variant_cannot_confirm_a_value(self):
        results = [dict(value=7200, digits="7200", variant="glyph_180", psm=psm)
                   for psm in (7, 8, 13)]
        self.assertIsNone(self.manager._select_signature_ocr_result(results))

    def test_empty_and_short_results_do_not_raise(self):
        self.manager._build_signature_ocr_variants = Mock(return_value=[])
        self.manager._save_signature_ocr_debug_variants = Mock()
        self.manager._run_signature_ocr_variants = Mock(return_value=[dict(value=123, digits="123")])
        self.assertIsNone(self.manager._ocr_signature_number(self.crop))

    def test_missing_tesseract_queues_vision(self):
        self.manager.signature_last_watch_area_rect = None
        self.manager.signature_icon_miss_count = 0
        self.manager.signature_ocr_unavailable_reported = False
        self.manager._prepare_signature_ocr_crop = Mock(return_value=(self.crop, (0, 0, 120, 36)))
        self.manager._ocr_signature_number = Mock(side_effect=mining.pytesseract.TesseractNotFoundError())
        self.manager._queue_signature_vision_analysis = Mock(return_value=None)
        with patch.object(mining.printr, "print_warn"):
            value, crop = self.manager._read_signature_value(self.crop)
        self.assertIsNone(value)
        self.assertIs(crop, self.crop)
        self.assertFalse(self.manager.signature_observer_config["local_signature_ocr_enabled"])
        self.manager._queue_signature_vision_analysis.assert_called_once()

    def test_local_failure_uses_verified_similar_vision_value(self):
        self.manager.signature_last_watch_area_rect = None
        self.manager.signature_icon_miss_count = 0
        self.manager._prepare_signature_ocr_crop = Mock(return_value=(self.crop, (0, 0, 120, 36)))
        self.manager._ocr_signature_number = Mock(return_value=None)
        self.manager._queue_signature_vision_analysis = Mock(return_value=21350)
        value, crop = self.manager._read_signature_value(self.crop)
        self.assertEqual(value, 21350)
        self.assertIs(crop, self.crop)

    def test_each_capture_resets_previous_support(self):
        self.manager.signature_last_ocr_value_support = {21350: 3}
        self.assertEqual(self.manager._read_signature_value(None), (None, None))
        self.assertEqual(self.manager.signature_last_ocr_value_support, {})

    def test_vision_worker_only_caches_and_never_displays_old_target(self):
        self._run_worker(dict(signature_value=21350))
        self.assertEqual(self.manager.signature_vision_cache["old-target"]["signature_value"], 21350)
        self.manager._handle_signature_vision_result.assert_not_called()

    def test_failed_vision_result_can_be_retried(self):
        self._run_worker(dict(signature_value=None))
        self.assertEqual(self.manager.signature_vision_cache, {})
        self.assertEqual(self.manager.signature_vision_queued_hashes, set())

    def test_stopped_worker_does_not_modify_new_worker_state(self):
        self._run_worker(dict(signature_value=21350), stopped_during_request=True)
        self.assertEqual(self.manager.signature_vision_cache, {})
        self.manager._handle_signature_vision_result.assert_not_called()

    def _run_worker(self, result, stopped_during_request=False):
        stop = threading.Event()
        self.manager.signature_vision_queue = queue.Queue()
        self.manager.signature_vision_queue.put(dict(image_hash="old-target"))
        self.manager.signature_vision_queued_hashes.add("old-target")
        def analyze(job):
            if stopped_during_request:
                stop.set()
            return result
        self.manager._analyze_signature_crop_with_vision = Mock(side_effect=analyze)
        self.manager._write_signature_vision_training_sample = Mock(side_effect=lambda *args: stop.set())
        self.manager._handle_signature_vision_result = Mock()
        self.manager._signature_vision_worker_loop(stop)
        self.assertEqual(self.manager.signature_vision_queue.unfinished_tasks, 0)

    def test_failed_similar_crop_does_not_suppress_retry(self):
        self.manager._remember_signature_vision_crop("failed", self.crop, 100)
        self.manager._verify_similar_signature_cache_crop = Mock(return_value=dict(verified=True))
        self.assertIsNone(self.manager._get_recent_similar_signature_vision_crop(self.crop, "new", 101))

    def test_similar_cache_rejects_a_changed_digit(self):
        templates = []
        for digits in ("58000", "56000"):
            crop = self.crop.copy()
            mining.cv2.putText(crop, digits, (3, 26), mining.cv2.FONT_HERSHEY_SIMPLEX,
                               0.65, (255, 255, 255), 1, mining.cv2.LINE_AA)
            templates.append(self.manager._signature_crop_match_template(crop))
        self.assertTrue(self.manager._verify_similar_signature_cache_crop(templates[0], templates[0])["verified"])
        self.assertFalse(self.manager._verify_similar_signature_cache_crop(*templates)["verified"])

    def test_cached_vision_digits_are_not_fuzzy_corrected(self):
        self.manager.signature_vision_cache["exact"] = dict(signature_value=1475)
        self.manager._correct_signature_ocr_value = Mock(return_value=11475)
        self.assertEqual(self.manager._get_cached_signature_vision_value(self.crop, "exact"), 1475)
        self.manager._correct_signature_ocr_value.assert_not_called()

    def test_cached_value_survives_hud_translation(self):
        first = self.crop.copy()
        mining.cv2.putText(first, "10800", (3, 24), mining.cv2.FONT_HERSHEY_SIMPLEX,
                           0.65, (255, 255, 255), 1, mining.cv2.LINE_AA)
        moved = mining.cv2.warpAffine(first, np.float32([[1, 0, 5], [0, 1, 3]]), (120, 36))
        self.manager._remember_signature_vision_crop("sent", first, 100)
        self.manager.signature_vision_cache["sent"] = dict(signature_value=10800)
        match = self.manager._get_recent_similar_signature_vision_crop(moved, "current", 101)
        self.assertTrue(match["verified"])
        self.assertEqual(match["image_hash"], "sent")

    def test_blank_crop_cannot_match_a_cached_value(self):
        template = self.manager._signature_crop_match_template(self.crop)
        self.assertFalse(self.manager._verify_similar_signature_cache_crop(template, template)["verified"])

    def test_reference_cache_refreshes_when_file_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reference.json"
            self.manager.signature_reference_path = str(path)
            path.write_text(json.dumps(dict(entries=[dict(resource="A")])), encoding="utf-8")
            first = self.manager.load_signature_reference()
            self.assertIs(self.manager.load_signature_reference(), first)
            path.write_text(json.dumps(dict(entries=[dict(resource="Changed")])), encoding="utf-8")
            self.assertEqual(self.manager.load_signature_reference(), [dict(resource="Changed")])

    def test_capture_preserves_watch_coordinates_with_small_source_image(self):
        window = Mock(left=10, top=20, width=1920, height=1080)
        self.manager._resolve_signature_watch_area_rect = Mock(return_value=(100, 200, 300, 210))
        with patch.object(mining.pygetwindow, "getActiveWindow", return_value=window), patch.object(
            mining.pyautogui, "screenshot", return_value=np.zeros((226, 422, 3), dtype=np.uint8)
        ) as screenshot:
            capture = self.manager._capture_signature_watch_area()
        screenshot.assert_called_once_with(region=(110, 212, 422, 226))
        self.assertEqual(capture["watch_rect"], (100, 200, 300, 210))
        self.assertEqual(capture["source_offset"], (0, 8))
        self.assertEqual(capture["watch_image"].shape, (210, 300, 3))


if __name__ == "__main__":
    unittest.main()
