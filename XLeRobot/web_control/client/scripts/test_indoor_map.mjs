import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const sourceDirectory = resolve(scriptDirectory, '../src/utils');
const backendMainPath = resolve(scriptDirectory, '../../server/main.py');
const modules = new Map();

function loadTypeScriptModule(name) {
  if (modules.has(name)) return modules.get(name);
  const filename = resolve(sourceDirectory, `${name}.ts`);
  const source = readFileSync(filename, 'utf8');
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  });
  const module = { exports: {} };
  const localRequire = request => {
    assert.equal(request, './indoorMap', `unexpected module dependency: ${request}`);
    return loadTypeScriptModule('indoorMap');
  };
  new Function('require', 'module', 'exports', outputText)(localRequire, module, module.exports);
  modules.set(name, module.exports);
  return module.exports;
}

const { findRoute, getDynamicObstaclePoints, isRouteBlockedByDynamicObstacle, STATIC_OBSTACLES, DYNAMIC_OBSTACLE_CLEARANCE } = loadTypeScriptModule('pathPlanner');
const { TABLE_APPROACH_DESTINATIONS, CHARGING_DESTINATION, INDOOR_MAP } = loadTypeScriptModule('indoorMap');

const backendMain = readFileSync(backendMainPath, 'utf8');
const backendBoundsBlock = backendMain.match(/MUJOCO_MAP_BOUNDS\s*=\s*\{([^}]+)\}/)?.[1];
assert.ok(backendBoundsBlock, 'backend must declare the MuJoCo map bounds used by its safety gate');
const backendBounds = Object.fromEntries(
  [...backendBoundsBlock.matchAll(/['"](min_x|max_x|min_y|max_y)['"]\s*:\s*(-?[\d.]+)/g)]
    .map(([, key, value]) => [key, Number(value)]),
);
assert.deepEqual(backendBounds, {
  min_x: INDOOR_MAP.bounds.minX,
  max_x: INDOOR_MAP.bounds.maxX,
  min_y: INDOOR_MAP.bounds.minY,
  max_y: INDOOR_MAP.bounds.maxY,
}, 'backend boundary gate and web planner must use identical map bounds');
const goals = [...TABLE_APPROACH_DESTINATIONS, CHARGING_DESTINATION];

for (const goal of goals) {
  const route = findRoute(INDOOR_MAP.start, goal);
  assert.ok(route, `expected a route to ${goal.name}`);
  const points = [INDOOR_MAP.start, ...route];
  for (let index = 1; index < points.length; index += 1) {
    const from = points[index - 1];
    const to = points[index];
    for (let ratio = 0; ratio <= 1; ratio += 0.02) {
      const point = {
        x: from.x + (to.x - from.x) * ratio,
        y: from.y + (to.y - from.y) * ratio,
      };
      for (const obstacle of STATIC_OBSTACLES) {
        assert.ok(
          Math.abs(point.x - obstacle.x) > obstacle.halfWidth + 0.8
            || Math.abs(point.y - obstacle.y) > obstacle.halfHeight + 0.8,
          `${goal.name} route intersects ${obstacle.name}`,
        );
      }
      assert.ok(point.x >= INDOOR_MAP.bounds.minX + 0.8 && point.x <= INDOOR_MAP.bounds.maxX - 0.8);
      assert.ok(point.y >= INDOOR_MAP.bounds.minY + 0.8 && point.y <= INDOOR_MAP.bounds.maxY - 0.8);
    }
  }
  console.log(`${goal.name}: route clear (${route.length} waypoints)`);
}

for (const table of INDOOR_MAP.tables) {
  assert.equal(findRoute(INDOOR_MAP.start, { x: table.x, y: table.y }), null, `${table.name} center must be blocked`);
}

const routeToCharging = findRoute(INDOOR_MAP.start, CHARGING_DESTINATION);
assert.ok(routeToCharging);
const staticMapReturns = [
  { x: -3.8, y: 6.8, source: 'static' },
  { x: 0, y: 0, source: 'static' },
];
assert.deepEqual(getDynamicObstaclePoints(staticMapReturns), [], 'mapped static geometry must not be re-added as a live obstacle');
assert.ok(findRoute(INDOOR_MAP.start, CHARGING_DESTINATION, staticMapReturns), 'static scan returns must not erase the mapped route');
const firstEnd = routeToCharging[0];
const dx = firstEnd.x - INDOOR_MAP.start.x;
const dy = firstEnd.y - INDOOR_MAP.start.y;
const segmentLength = Math.hypot(dx, dy);
const midpoint = { x: (firstEnd.x + INDOOR_MAP.start.x) / 2, y: (firstEnd.y + INDOOR_MAP.start.y) / 2 };
const mobileReturn = [{
  x: midpoint.x - dy / segmentLength * DYNAMIC_OBSTACLE_CLEARANCE * 0.9,
  y: midpoint.y + dx / segmentLength * DYNAMIC_OBSTACLE_CLEARANCE * 0.9,
}];
assert.deepEqual(getDynamicObstaclePoints([...staticMapReturns, { ...mobileReturn[0], source: 'dynamic' }]), mobileReturn);
assert.equal(isRouteBlockedByDynamicObstacle(INDOOR_MAP.start, routeToCharging, 0, mobileReturn), true,
  'live obstacle inside A* dynamic margin must trigger replan');
const outsideMargin = [{
  x: midpoint.x - dy / segmentLength * (DYNAMIC_OBSTACLE_CLEARANCE + 0.01),
  y: midpoint.y + dx / segmentLength * (DYNAMIC_OBSTACLE_CLEARANCE + 0.01),
}];
assert.equal(isRouteBlockedByDynamicObstacle(INDOOR_MAP.start, routeToCharging, 0, outsideMargin), false,
  'route following and A* must use the same dynamic clearance');
const dynamicBlock = { x: -4.5, y: -1.0 };
assert.equal(isRouteBlockedByDynamicObstacle(INDOOR_MAP.start, routeToCharging, 0, [dynamicBlock]), true,
  'the obstacle must lie inside the followed route safety margin');
const reroute = findRoute(INDOOR_MAP.start, CHARGING_DESTINATION, [{ ...dynamicBlock, source: 'dynamic' }]);
assert.ok(reroute, 'a single moving obstacle should trigger a safe alternate path when available');
assert.notDeepEqual(reroute, routeToCharging, 'the obstacle response must not return the blocked original route');
console.log('static LiDAR deduplication and dynamic clearance regression: passed');
