// Line-oriented SQL bridge for Python application tests against in-memory Postgres.
// No server socket, environment loading, remote connection or persistent database.
const readline = require('node:readline');
const { PGlite } = require(process.env.PGLITE_TEST_MODULE);
const db = new PGlite();
(async () => {
  await db.waitReady;
  const input = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
  for await (const line of input) {
    try {
      const command = JSON.parse(line);
      const result = command.mode === 'exec' ? await db.exec(command.sql) : await db.query(command.sql, command.args || []);
      process.stdout.write(JSON.stringify({ rows: result.rows || [], ok: true }) + '\n');
    } catch (error) {
      process.stdout.write(JSON.stringify({ ok: false, code: error.code, message: error.message }) + '\n');
    }
  }
  await db.close();
})().catch(error => { process.stderr.write(String(error)); process.exitCode = 1; });
