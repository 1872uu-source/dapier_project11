# Indoor simulation map and SLAM handoff

The browser's `mujoco_static` map and `simulation/mujoco/scene.xml` use the
MuJoCo chassis/map frame (`xlerobot_map`). The chassis has a fixed +90 degree
world rotation, so a map point `(x, y)` is placed in MuJoCo world coordinates
as `(-y, x)`. MuJoCo range-hit points are converted back to `(world_y,
-world_x)` by `obstacle_scan.py`.

The current room is 10 m wide by 12 m long: `x=[-5,5]`, `y=[-4,8]`. Its south
wall has a centered 1.8 m doorway. The three table footprints and their safe
approach points are defined in `client/src/utils/indoorMap.ts`; the planner
uses these footprints and the MuJoCo XML mirrors them as collidable boxes.
The planned table target is offset from the tabletop and includes the planner's
robot-clearance margin.

`client/src/types/index.ts` defines a normalized `OccupancyGridMap` contract
for a future ROS 2 `nav_msgs/OccupancyGrid` adapter. The adapter should preserve
the ROS frame ID, map origin and yaw, resolution, timestamp, and row-major cell
values. The renderer and destination storage should then consume a common map
frame transform instead of treating the static MuJoCo room as a live SLAM map.
Future `/scan` and `/map` subscriptions and Nav2 goal dispatch are not enabled
by this simulation-map change.

Saved destinations remain browser-local and keep full numeric precision in
localStorage. The map displays rounded coordinates only. Legacy saved points
are still read, but route planning safely refuses points outside the current
room or inside an obstacle.
