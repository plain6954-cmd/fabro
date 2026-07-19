import { runDjango } from './django';

export default async function globalTeardown() {
  runDjango(['flush', '--noinput']);
}
