"""MuJoCo regression scenarios for multi-height range sensing."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import mujoco

from obstacle_scan import LAYER_HEIGHTS_M, scan_obstacles


SCENE_PATH = Path(__file__).resolve().parents[1] / "scene.xml"


class ObstacleScanRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = SCENE_PATH.read_text(encoding="utf-8")
        marker = "  </worldbody>"
        test_body = '''
    <body name="regression_moving_obstacle" mocap="true" pos="-2 0 0">
      <geom name="regression_moving_geom" type="box" pos="0 0 0.5"
        size="0.25 0.25 0.5" rgba="0.95 0.25 0.12 1" contype="1" conaffinity="1"/>
    </body>
'''
        if marker not in source:
            raise RuntimeError("Could not insert the moving-obstacle regression body")
        cls.temp_scene = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix="_range_regression.xml",
            prefix=".tmp_",
            dir=SCENE_PATH.parent,
            delete=False,
        )
        cls.temp_scene.write(source.replace(marker, test_body + marker, 1))
        cls.temp_scene.close()
        cls.model = mujoco.MjModel.from_xml_path(cls.temp_scene.name)
        cls.data = mujoco.MjData(cls.model)
        cls.mocap_id = int(cls.model.body("regression_moving_obstacle").mocapid[0])

    @classmethod
    def tearDownClass(cls):
        Path(cls.temp_scene.name).unlink(missing_ok=True)

    def scan_at(self, logical_x: float, logical_y: float):
        # Logical (x, y) maps to world (-y, x) for this chassis orientation.
        self.data.mocap_pos[self.mocap_id] = [-logical_y, logical_x, 0.0]
        mujoco.mj_forward(self.model, self.data)
        return scan_obstacles(self.model, self.data)

    @staticmethod
    def hits_near(hits, x: float, y: float):
        return [
            hit for hit in hits
            if abs(hit["x"] - x) <= 0.35 and abs(hit["y"] - y) <= 0.5
        ]

    def test_scan_reports_configured_coverage_and_bounded_duration(self):
        hits, status = self.scan_at(0.0, 2.0)
        self.assertEqual(status["beam_count"], 180)
        self.assertEqual(status["ray_count"], 180 * len(LAYER_HEIGHTS_M))
        self.assertEqual(status["range_m"], 8.0)
        self.assertGreater(status["hit_count"], 0)
        self.assertTrue(hits)
        self.assertGreaterEqual(status["scan_duration_ms"], 0.0)
        self.assertLessEqual(status["scan_duration_ms"], 80.0)

    def test_scan_detects_obstacle_at_multiple_heights(self):
        hits, _ = self.scan_at(0.0, 2.0)
        obstacle_hits = self.hits_near(hits, 0.0, 2.0)
        detected_heights = {hit["height"] for hit in obstacle_hits}
        self.assertGreaterEqual(len(detected_heights), 3)

    def test_static_tables_are_marked_static_and_mocap_obstacle_dynamic(self):
        self.data.mocap_pos[self.mocap_id] = [20.0, 20.0, 0.0]
        mujoco.mj_forward(self.model, self.data)
        static_hits, _ = scan_obstacles(self.model, self.data)
        table_hits = self.hits_near(static_hits, 0.0, 3.0)
        self.assertTrue(table_hits)
        self.assertTrue(all(hit["source"] == "static" for hit in table_hits))

        dynamic_hits, _ = self.scan_at(0.0, 2.0)
        self.assertTrue(self.hits_near(dynamic_hits, 0.0, 2.0))
        self.assertTrue(any(hit["source"] == "dynamic" for hit in dynamic_hits))

    def test_scan_detects_obstacle_beyond_previous_six_meter_limit(self):
        # Keep the far target out of the direct ray behind table 2.
        hits, _ = self.scan_at(2.5, 7.5)
        distant_hits = self.hits_near(hits, 2.5, 7.5)
        self.assertTrue(distant_hits)
        self.assertTrue(any(6.0 < hit["distance"] <= 8.0 for hit in distant_hits))

    def test_scan_tracks_moving_obstacle_and_clears_its_old_position(self):
        first_hits, _ = self.scan_at(0.0, 2.0)
        moved_hits, _ = self.scan_at(2.0, 3.0)
        self.assertTrue(self.hits_near(first_hits, 0.0, 2.0))
        self.assertTrue(self.hits_near(moved_hits, 2.0, 3.0))
        self.assertFalse(self.hits_near(moved_hits, 0.0, 2.0))


if __name__ == "__main__":
    unittest.main()
