import type { Config } from 'jest';

const config: Config = {
  testEnvironment: 'jsdom',
  transform: {
    // Local wrapper around esbuild-jest that also defines import.meta.env;
    // see jest-esbuild-transformer.cjs
    '^.+\\.(ts|tsx|js|jsx)$': '<rootDir>/jest-esbuild-transformer.cjs',
  },
  moduleNameMapper: {
    // Resource-extension rules must come BEFORE the '@/...' alias rule: an
    // aliased asset (e.g. '@/assets/icon/brand-lockup.png') matches both, and
    // Jest uses the first matching pattern, so a resource rule placed last
    // never fires and Jest tries to execute the binary as JavaScript.
    '\\.(css|less|scss|sass)$': '<rootDir>/__mocks__/styleMock.js',
    '\\.(jpg|jpeg|png|gif|svg|webp)$': '<rootDir>/__mocks__/fileMock.js',
    // Drags the app shell (routes/react-router) into jsdom; see __mocks__
    '^@/components/layout-recognize-form-field$':
      '<rootDir>/__mocks__/layout-recognize-form-field.js',
    '^@/(.*)$': '<rootDir>/src/$1',
    '^human-id$': '<rootDir>/__mocks__/human-id.js',
  },
  setupFilesAfterEnv: ['<rootDir>/jest-setup.ts'],
  // Jest's default excludes everything under node_modules from transformation,
  // but the unified/remark/rehype ecosystem ships ESM-only packages. Left
  // untransformed they reach Jest's CJS runtime as `export {...}` and abort the
  // importing suite with "Unexpected token 'export'" — which is why the
  // highlight-markdown suite (the only coverage of the markdown -> math ->
  // KaTeX pipeline) never ran. The transformer already emits CJS, so these
  // simply need to be let through. Kept as an allow-list of families rather
  // than disabling the default entirely, so ordinary node_modules stay
  // untransformed and the suite does not slow down.
  transformIgnorePatterns: [
    '/node_modules/(?!(?:hast-util-[^/]+|mdast-util-[^/]+|micromark[^/]*|unist-util-[^/]+|estree-util-[^/]+|remark-[^/]+|rehype-[^/]+|vfile[^/]*|unified|react-markdown|property-information|space-separated-tokens|comma-separated-tokens|html-void-elements|web-namespaces|zwitch|ccount|character-entities[^/]*|character-reference-invalid|decode-named-character-reference|devlop|longest-streak|markdown-table|trim-lines|bail|trough|is-plain-obj|is-alphabetical|is-decimal|is-hexadecimal|parse5|hastscript|katex|escape-string-regexp|html-url-attributes|parse-entities|stringify-entities|is-absolute-url|url-join|style-to-object|inline-style-parser|entities)/)',
  ],
  collectCoverageFrom: [
    'src/**/*.{ts,tsx,js,jsx}',
    '!src/.umi/**',
    '!src/.umi-test/**',
    '!src/.umi-production/**',
    '!**/*.d.ts',
    '!coverage/**',
    '!dist/**',
    '!config/**',
    '!mock/**',
  ],
  coverageThreshold: {
    global: {
      lines: 1,
    },
  },
  testPathIgnorePatterns: ['/node_modules/', '/dist/'],
};

export default config;
