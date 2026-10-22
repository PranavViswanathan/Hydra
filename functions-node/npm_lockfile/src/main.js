/**
 * Regenerate a package-lock.json from a package.json (PROJECT.md 6.4).
 *
 * The Python runtime has no npm, so this is the one Node function in the
 * project. It holds no business logic: manifest in, lockfile out.
 *
 * --ignore-scripts is mandatory (safety rule 5): VulnAgent never executes
 * code from a target repository.
 */

import { execFile } from 'node:child_process';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { promisify } from 'node:util';

const run = promisify(execFile);

const NPM_ARGS = [
  'install',
  '--package-lock-only',
  '--ignore-scripts',
  '--no-audit',
  '--no-fund',
];
const TIMEOUT_MS = 120_000;

export default async ({ req, res, log, error }) => {
  let payload;
  try {
    payload = typeof req.body === 'string' ? JSON.parse(req.body) : req.body;
  } catch {
    return res.json({ error: 'body must be JSON' }, 400);
  }

  const packageJson = payload?.package_json;
  if (typeof packageJson !== 'string' || packageJson.trim() === '') {
    return res.json({ error: 'package_json is required' }, 400);
  }

  const workspace = await mkdtemp(join(tmpdir(), 'vulnagent-'));
  try {
    await writeFile(join(workspace, 'package.json'), packageJson, 'utf8');
    if (typeof payload.package_lock === 'string' && payload.package_lock.trim() !== '') {
      await writeFile(join(workspace, 'package-lock.json'), payload.package_lock, 'utf8');
    }

    const started = Date.now();
    await run('npm', NPM_ARGS, { cwd: workspace, timeout: TIMEOUT_MS });
    log(`regenerated the lockfile in ${Date.now() - started}ms`);

    const lockfile = await readFile(join(workspace, 'package-lock.json'), 'utf8');
    return res.json({ package_lock: lockfile });
  } catch (failure) {
    error(`npm failed: ${failure.message}`);
    return res.json({ error: `npm failed: ${failure.stderr || failure.message}` }, 500);
  } finally {
    await rm(workspace, { recursive: true, force: true });
  }
};
