"""Convert between the web map, robot body, and MuJoCo world frames.

The web map is rotated +90 degrees relative to MuJoCo world:
map (x, y) -> world (-y, x).  The chassis MJCF has the same fixed +90 degree
orientation, so the hinge joint position is yaw relative to the map frame.
All distances are metres, angles are radians, and velocities are m/s.
"""

from __future__ import annotations

import math


def map_to_slide(map_x: float, map_y: float) -> tuple[float, float]:
    """Convert map-frame position/velocity to MuJoCo world slide axes."""
    return -map_y, map_x


def slide_to_map(slide_x: float, slide_y: float) -> tuple[float, float]:
    """Convert MuJoCo world slide position/velocity to the web map frame."""
    return slide_y, -slide_x


def body_velocity_to_slide(forward: float, left: float, yaw: float) -> tuple[float, float]:
    """Convert body forward/left velocity to MuJoCo world slide axes.

    ``yaw`` is the chassis hinge position, which is expressed relative to the
    fixed +90 degree chassis orientation and therefore equals map-frame yaw.
    """
    cosine = math.cos(yaw)
    sine = math.sin(yaw)
    map_x = forward * cosine - left * sine
    map_y = forward * sine + left * cosine
    return map_to_slide(map_x, map_y)


def slide_delta_to_body(dx: float, dy: float, yaw: float) -> tuple[float, float]:
    """Resolve a MuJoCo world slide delta into robot-relative forward/left."""
    map_x, map_y = slide_to_map(dx, dy)
    cosine = math.cos(yaw)
    sine = math.sin(yaw)
    return (
        map_x * cosine + map_y * sine,
        -map_x * sine + map_y * cosine,
    )
