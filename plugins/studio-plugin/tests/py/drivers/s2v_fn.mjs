// Calls one function of script2video's built CLI modules:
//   node s2v_fn.mjs S2V_REPO gitignore DIR              → ensureGitignore(DIR)
//   node s2v_fn.mjs S2V_REPO actor-hold LOCK FILE       → take LOCK, print token, hold until FILE exists
//   node s2v_fn.mjs S2V_REPO actor-try LOCK [TOKEN]     → print acquireDir's status (releases if acquired)
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const [repo, what, a, b] = process.argv.slice(2);
const mod = (m) => import(pathToFileURL(join(repo, 'packages/cli/dist', m)).href);
const sleep = (ms) => Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
if (what === 'gitignore') {
  (await mod('character-gen/state.js')).ensureGitignore(a);
} else {
  const { acquireDir, procStart, releaseDir } = await mod('dir-lock.js');
  const fields = { pid: process.pid, pid_start: procStart(process.pid), cmd: 'node race' };
  const r = acquireDir(a, fields, { envToken: what === 'actor-try' ? b : undefined });
  console.log(JSON.stringify({ status: r.status, token: r.token ?? null }));
  if (what === 'actor-hold') {
    while (!existsSync(b)) sleep(20);
    releaseDir(a, r.token);
  } else if (r.status === 'acquired') releaseDir(a, r.token);
}
