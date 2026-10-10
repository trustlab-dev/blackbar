import '@testing-library/jest-dom';
import { Blob as NodeBlob, File as NodeFile } from 'node:buffer';
import { beforeAll, afterAll, afterEach } from 'vitest';
import { server } from './test-utils/msw-handlers';

// jsdom (>=26) installs its own global Blob/File. They are not compatible with
// the undici body-extraction that MSW's XHR interceptor uses to deliver mocked
// responses ("TypeError: object.stream is not a function"), which silently
// breaks intercepted blob/error responses. Use Node's undici-native Blob/File
// so MSW can build responses; jsdom's URL.createObjectURL still accepts these.
globalThis.Blob = NodeBlob as unknown as typeof globalThis.Blob;
globalThis.File = NodeFile as unknown as typeof globalThis.File;

// Unhandled requests must fail the test that made them. MSW's 'error'
// strategy only errors the request itself, which a test expecting a rejected
// call (e.g. `rejects.toThrow()`) would treat as a pass. So keep the default
// error (logged, request rejected) and also record the request, then fail the
// test in afterEach.
const unhandledRequests: string[] = [];

beforeAll(() =>
  server.listen({
    onUnhandledFrame({ frame, defaults }) {
      if (frame.protocol === 'http') {
        const { request } = frame.data as { request: Request };
        unhandledRequests.push(`${request.method} ${request.url}`);
      } else {
        unhandledRequests.push(`${frame.protocol} frame`);
      }
      defaults.error();
    },
  }),
);
afterEach(() => {
  server.resetHandlers();
  // Capability-link pages stash tokens here (utils/capabilityUrl.ts).
  sessionStorage.clear();
  if (unhandledRequests.length > 0) {
    const requests = unhandledRequests.splice(0);
    throw new Error(
      `[MSW] Unhandled request(s) during this test:\n  ${requests.join('\n  ')}`,
    );
  }
});
afterAll(() => server.close());
