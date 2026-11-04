import assert from 'node:assert/strict';

assert.match(process.version, /^v24\./);
assert.ok(process.execArgv.includes('--max-old-space-size=409'));
assert.equal(process.pid, 1);
console.log(`运行镜像启动验证通过：Node.js ${process.version}，内存参数为 409 MB。`);
