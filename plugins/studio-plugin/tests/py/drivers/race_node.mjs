// Lock race driver (Node side, script2video's built dir-lock.js):
//   node race_node.mjs S2V_REPO LOCK BARRIER LOG LOOPS HOLD_MS
import { appendFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const [repo, lock, barrier, log, loops, hold] = process.argv.slice(2);
const { acquireDir, procStart, readOwner, releaseDir } = await import(
  pathToFileURL(join(repo, 'packages/cli/dist/dir-lock.js')).href
);
const sleep = (ms) => Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
const start = procStart(process.pid);
const note = (l) => appendFileSync(log, `${l}\n`);
note(`ready js${process.pid}`);
while (!existsSync(barrier)) sleep(2);
const deadline = Date.now() + 60000;
for (let k = 0; k < Number(loops); k++) {
  let r;
  for (;;) {
    r = acquireDir(lock, { kind: 'tts', pid: process.pid, pid_start: start, holder: 'race-js' });
    if (Number(loops) === 1 || r.status === 'acquired' || Date.now() > deadline) break;
    sleep(25);
  }
  if (r.status === 'acquired') {
    note(`enter js${process.pid}`);
    sleep(Number(hold));
    note(`exit js${process.pid} stillmine=${readOwner(lock)?.token === r.token}`);
    releaseDir(lock, r.token);
  }
  note(`result js${process.pid} ${r.status}`);
}
