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

beforeAll(() => server.listen({ onUnhandledRequest: 'warn' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
