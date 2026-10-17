import { build } from 'esbuild';
import { mkdtemp, readdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const tests = (await readdir(join(root, 'src'), { recursive: true }))
  .filter(path => /\.test\.tsx?$/.test(path))
  .map(path => join(root, 'src', path));
if (tests.length === 0) throw new Error('No frontend tests found');

const output = await mkdtemp(join(tmpdir(), 'bookkeep-frontend-tests-'));

try {
  await build({
    absWorkingDir: root,
    entryPoints: tests,
    outdir: output,
    outExtension: { '.js': '.cjs' },
    bundle: true,
    platform: 'node',
    format: 'cjs',
    jsx: 'automatic',
    define: { 'import.meta.env': JSON.stringify({ PROD: true }) },
  });
  const compiled = (await readdir(output, { recursive: true }))
    .filter(path => path.endsWith('.cjs'))
    .map(path => join(output, path));
  const result = spawnSync(process.execPath, ['--test', ...compiled], {
    cwd: root,
    stdio: 'inherit',
  });
  if (result.error) throw result.error;
  process.exitCode = result.status ?? 1;
} finally {
  await rm(output, { recursive: true, force: true });
}
