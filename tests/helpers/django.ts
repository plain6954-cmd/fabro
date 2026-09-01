import { execFileSync } from 'child_process';
import { existsSync } from 'fs';
import { testUser } from './testData';

const localPython = process.platform === 'win32'
  ? (existsSync('.\\env\\Scripts\\python.exe') ? '.\\env\\Scripts\\python.exe' : '.\\.venv\\Scripts\\python.exe')
  : (existsSync('./env/bin/python') ? './env/bin/python' : './.venv/bin/python');

const pythonCommand = process.env.PYTHON || localPython;
const testEnvironment = {
  ...process.env,
  E2E_TESTING: 'True',
  E2E_USERNAME: testUser.username,
  E2E_PASSWORD: testUser.password,
  E2E_EMAIL: testUser.email
};

export function runDjango(args: string[]) {
  execFileSync(pythonCommand, ['manage.py', ...args], {
    stdio: 'inherit',
    env: testEnvironment
  });
}

export function runDjangoCode(code: string) {
  runDjango(['shell', '-c', code]);
}
