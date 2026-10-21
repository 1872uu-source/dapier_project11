"""Multi-height 2D range scan utilities shared by the MuJoCo host and tests."""

from __future__ import annotations

import math
import time

import mujoco
import numpy as np


BEAM_COUNT = 180
LAYER_HEIGHTS_M = (0.12, 0.38, 0.72)
MAX_RANGE_M = 8.0


def scan_obstacles(model, data):
    """Cast a 360-degree scan at several heights and return map-frame hit points."""
    started = time.perf_counter()
    chassis_id = model.body("chassis").id
    chassis_origin = data.xpos[chassis_id].copy()
    obstacle_hits = []

    for layer_height in LAYER_HEIGHTS_M:
        origin = chassis_origin.copy()
        origin[2] += layer_height
        for beam in range(BEAM_COUNT):
            angle = 2.0 * math.pi * beam / BEAM_COUNT
            direction = np.array(
                [math.cos(angle), math.sin(angle), 0.0],
                dtype=np.float64,
            )
            nearest_hit = None
            # Query both ray modes and keep the nearest geometry. Classify the
            # hit by its owning body below because mocap objects may be returned
            # from either mode depending on the MuJoCo model.
            for include_static in (True, False):
                geom_id = np.array([-1], dtype=np.int32)
                ray_distance = float(mujoco.mj_ray(
                    model,
                    data,
                    origin,
                    direction,
                    None,
                    include_static,
                    chassis_id,
                    geom_id,
                ))
                if ray_distance >= 0.12 and (nearest_hit is None or ray_distance < nearest_hit[0]):
                    nearest_hit = (ray_distance, int(geom_id[0]))
            if nearest_hit is None:
                continue
            distance, geom_id = nearest_hit
            if distance > MAX_RANGE_M:
                continue
            source = "static" if int(model.geom_bodyid[geom_id]) == 0 else "dynamic"

            world_x = origin[0] + direction[0] * distance
            world_y = origin[1] + direction[1] * distance
            # Chassis logical (x, y) is world (y, -x) after its fixed +90 degree rotation.
            obstacle_hits.append({
                "x": round(float(world_y), 3),
                "y": round(float(-world_x), 3),
                "distance": round(distance, 3),
                "height": round(float(origin[2]), 3),
                "source": source,
            })

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return obstacle_hits, {
        "beam_count": BEAM_COUNT,
        "layer_heights_m": list(LAYER_HEIGHTS_M),
        "ray_count": BEAM_COUNT * len(LAYER_HEIGHTS_M),
        "range_m": MAX_RANGE_M,
        "hit_count": len(obstacle_hits),
        "scan_duration_ms": round(elapsed_ms, 2),
    }
