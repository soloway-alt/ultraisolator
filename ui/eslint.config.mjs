import js from '@eslint/js';
import react from 'eslint-plugin-react';
import reactHooks from 'eslint-plugin-react-hooks';
import unusedImports from 'eslint-plugin-unused-imports';
import globals from 'globals';

export default [
  {
    ignores: [
      'dist/**',
      'dist-packaged/**',
      'node_modules/**',
      '.runtime/**',
      'playwright-report/**',
      'test-results/**',
      'tests/visual/**/*-snapshots/**'
    ]
  },
  js.configs.recommended,
  {
    files: ['**/*.{js,jsx,mjs}'],
    languageOptions: {
      ecmaVersion: 2023,
      sourceType: 'module',
      parserOptions: { ecmaFeatures: { jsx: true } },
      globals: { ...globals.browser, ...globals.node }
    },
    plugins: {
      react,
      'react-hooks': reactHooks,
      'unused-imports': unusedImports
    },
    settings: { react: { version: 'detect' } },
    rules: {
      'react/jsx-uses-react': 'error',
      'react/jsx-uses-vars': 'error',
      'react-hooks/rules-of-hooks': 'error',
      // The dependency-array gaps were fixed deliberately (unstable
      // `Array.isArray(x) ? x : []` fallbacks moved inside the callbacks);
      // error keeps new violations from slipping through silently.
      'react-hooks/exhaustive-deps': 'error',
      'unused-imports/no-unused-imports': 'error',
      // Interpolation goes through t(key, fallback, params); string-replacing
      // {{tokens}} on translated output bypasses the catalog parameters.
      'no-restricted-syntax': [
        'error',
        {
          selector: "CallExpression[callee.property.name='replace'][arguments.0.value=/^\\{\\{/]",
          message: 'Use the t(key, fallback, params) third argument instead of .replace(\'{{token}}\', …).'
        }
      ],
      'no-unused-vars': [
        'error',
        {
          argsIgnorePattern: '^_',
          varsIgnorePattern: '^_',
          caughtErrorsIgnorePattern: '^_'
        }
      ]
    }
  },
  {
    // CommonJS main-process and tooling files.
    files: ['electron-main.js', 'backend-runtime.js', 'electron-preload.js', 'main/**/*.js', 'scripts/**/*.js', 'playwright.config.js'],
    languageOptions: {
      sourceType: 'commonjs',
      globals: { ...globals.node }
    }
  }
];
