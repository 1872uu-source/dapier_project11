import assert from 'node:assert/strict';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const sourcePath = resolve(scriptDirectory, '../src/utils/navigationController.ts');
const source = ts.transpileModule((await import('node:fs')).readFileSync(sourcePath, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const module = { exports: {} };
new Function('require', 'module', 'exports', source)(() => { throw new Error('unexpected import'); }, module, module.exports);
const { computeWaypointCommand, NavigationMotionGuard, shouldStopForDriveFeedback, updateTurnDirection, wrapAngle } = module.exports;
const closeTo = (actual, expected, epsilon = 1e-9) => assert.ok(Math.abs(actual - expected) < epsilon, `${actual} != ${expected}`);
const sample = values => ({ commandedAngular: 0, actualAngular: 0, ...values });

for (const yaw of [0, Math.PI / 2, Math.PI, -Math.PI / 2]) {
  for (const target of [{ x: 1, y: 0 }, { x: -1, y: 0 }, { x: 0, y: 1 }, { x: 0, y: -1 }]) {
    const desiredYaw = Math.atan2(target.y, target.x);
    const command = computeWaypointCommand({ x: 0, y: 0, yaw }, target, 0.5);
    const error = wrapAngle(desiredYaw - yaw);
    if (Math.abs(error) <= 0.2) {
      assert.equal(command.phase, 'driving');
      closeTo(command.linearX / Math.hypot(command.linearX, command.linearY), target.x);
      closeTo(command.linearY / Math.hypot(command.linearX, command.linearY), target.y);
    } else {
      assert.equal(command.phase, 'aligning');
      closeTo(command.linearX, 0);
      closeTo(command.linearY, 0);
      assert.equal(Math.sign(command.angular), Math.sign(error));
    }
  }
}

// The old inline law emitted +/-0.08 rad/s even though its UI classified
// these small errors as straight-ahead, allowing tiny pose noise to reverse yaw.
assert.equal(Math.sign(0.05 * 1.6), 1);
assert.equal(Math.sign(-0.05 * 1.6), -1);
assert.equal(computeWaypointCommand({ x: 0, y: 0, yaw: Math.PI / 2 + 0.05 }, { x: 0, y: 2 }, 0.5).angular, 0);

const needsAlignment = computeWaypointCommand({ x: 0, y: 0, yaw: 0 }, { x: 0, y: 2 }, 0.5);
assert.equal(needsAlignment.phase, 'aligning');
closeTo(needsAlignment.linearX, 0);
closeTo(needsAlignment.linearY, 0);
assert.ok(needsAlignment.angular > 0, 'map +Y requires a positive left turn from yaw zero');
const settled = computeWaypointCommand({ x: 0, y: 0, yaw: Math.PI / 2 + 0.05 }, { x: 0, y: 2 }, 0.5);
assert.equal(settled.phase, 'driving');
closeTo(settled.angular, 0);

// Measured yaw rate must damp rotation and block translation until settled.
const stillRotating = computeWaypointCommand(
  { x: 0, y: 0, yaw: Math.PI / 2 + 0.05 }, { x: 0, y: 2 }, 0.5, null, 0.2,
);
assert.equal(stillRotating.phase, 'braking');
closeTo(stillRotating.linearX, 0);
closeTo(stillRotating.linearY, 0);
assert.ok(stillRotating.angular < 0, 'positive residual yaw rate must receive a counter-rotation command');
assert.equal(stillRotating.damping, true);
const pdTurn = computeWaypointCommand({ x: 0, y: 0, yaw: Math.PI / 2 - 0.4 }, { x: 0, y: 2 }, 0.5, null, 0.2);
closeTo(pdTurn.angular, 1.25 * 0.4 - 0.8 * 0.2);
const saturatedTurn = computeWaypointCommand({ x: 0, y: 0, yaw: 0 }, { x: 0, y: 2 }, 0.5, null, -0.4);
assert.ok(saturatedTurn.angular <= 0.55);
const movingAtGoal = computeWaypointCommand({ x: 0, y: 0, yaw: 0 }, { x: 0.1, y: 0 }, 0.5, null, 0.2);
assert.equal(movingAtGoal.phase, 'braking', 'arrival must wait for yaw rate to settle');
closeTo(movingAtGoal.linearX, 0);
const stoppedAtGoal = computeWaypointCommand({ x: 0, y: 0, yaw: 0 }, { x: 0.1, y: 0 }, 0.5, null, 0.04);
assert.equal(stoppedAtGoal.phase, 'arrived');

assert.ok(Math.abs(wrapAngle(-Math.PI - 0.01) - (Math.PI - 0.01)) < 1e-9);
assert.equal(updateTurnDirection(3.13, null), 1);
assert.equal(updateTurnDirection(-3.13, 1), 1, 'wrap noise must not reverse a committed 180-degree turn');
assert.equal(updateTurnDirection(2.4, 1), 1, 'turn hysteresis persists in the dead band');
assert.equal(updateTurnDirection(2.1, 1), null, 'turn direction resets after meaningful alignment');
for (const status of ['rejected', 'error', 'throttled', 'rate_limited', 'stale']) {
  assert.equal(shouldStopForDriveFeedback(status), true, `${status} feedback must stop following`);
}
for (const status of ['pending', 'accepted', 'success']) {
  assert.equal(shouldStopForDriveFeedback(status), false, `${status} feedback must not stop following`);
}

const guard = new NavigationMotionGuard();
for (const nowMs of [0, 300, 650]) {
  assert.equal(guard.observe(sample({ nowMs, distance: 2, commandedX: 0.2, commandedY: 0, actualX: -0.1, actualY: 0 })), null);
}
assert.match(guard.observe(sample({ nowMs: 950, distance: 2, commandedX: 0.2, commandedY: 0, actualX: -0.1, actualY: 0 })), /반대/);
guard.reset();
assert.equal(guard.observe(sample({ nowMs: 0, distance: 2, commandedX: 0.2, commandedY: 0, actualX: 0.1, actualY: 0 })), null);
assert.equal(guard.observe(sample({ nowMs: 300, distance: 2.03, commandedX: 0.2, commandedY: 0, actualX: 0.1, actualY: 0 })), null);
assert.equal(guard.observe(sample({ nowMs: 1000, distance: 2.05, commandedX: 0.2, commandedY: 0, actualX: 0.1, actualY: 0 })), null);
assert.match(guard.observe(sample({ nowMs: 2000, distance: 2.08, commandedX: 0.2, commandedY: 0, actualX: 0.1, actualY: 0 })), /증가/);
guard.reset();
for (const nowMs of [0, 350, 700]) {
  assert.equal(guard.observe(sample({ nowMs, distance: 2, commandedX: 0, commandedY: 0, actualX: 0, actualY: 0, commandedAngular: 0.3, actualAngular: -0.2 })), null);
}
assert.match(guard.observe(sample({ nowMs: 950, distance: 2, commandedX: 0, commandedY: 0, actualX: 0, actualY: 0, commandedAngular: 0.3, actualAngular: -0.2 })), /yaw 변화 방향/);
guard.reset();
for (const [nowMs, actualAngular] of [[0, 0.3], [250, 0.22], [500, 0.14], [750, 0.07]]) {
  assert.equal(guard.observe(sample({
    nowMs, distance: 2, commandedX: 0, commandedY: 0, actualX: 0, actualY: 0,
    commandedAngular: -0.2, actualAngular, damping: true,
  })), null, 'measured, reducing yaw rate should permit intentional counter-steering');
}
guard.reset();
for (const nowMs of [0, 300, 650]) {
  assert.equal(guard.observe(sample({
    nowMs, distance: 2, commandedX: 0, commandedY: 0, actualX: 0, actualY: 0,
    commandedAngular: -0.2, actualAngular: 0.2, damping: true,
  })), null);
}
assert.match(guard.observe(sample({
  nowMs: 950, distance: 2, commandedX: 0, commandedY: 0, actualX: 0, actualY: 0,
  commandedAngular: -0.2, actualAngular: 0.2, damping: true,
})), /감속 명령에도/);
guard.reset();
for (const nowMs of [0, 300, 600]) {
  assert.equal(guard.observe(sample({ nowMs, distance: 2, commandedX: 0, commandedY: 0, actualX: 0, actualY: 0, commandedAngular: 0, actualAngular: 0.2 })), null);
}
assert.match(guard.observe(sample({ nowMs: 750, distance: 2, commandedX: 0, commandedY: 0, actualX: 0, actualY: 0, commandedAngular: 0, actualAngular: 0.2 })), /계속 회전/);

console.log('navigation controller: cardinal map movement, yaw alignment, wrap stability, persistent feedback guards passed');
