import eslint from '@eslint/js'
import prettier from 'eslint-config-prettier'
import globals from 'globals'
import tseslint from 'typescript-eslint'
import vue from 'eslint-plugin-vue'

export default tseslint.config(
  {
    ignores: [
      '.quasar/**',
      'dist/**',
      'node_modules/**',
      'playwright-report/**',
      'src-electron/**',
      'src-capacitor/www/**',
      'src-capacitor/android/**',
      'src-capacitor/ios/**',
    ],
  },
  eslint.configs.recommended,
  ...tseslint.configs.recommended,
  ...vue.configs['flat/essential'],
  {
    files: ['**/*.{ts,vue}'],
    languageOptions: {
      globals: { ...globals.browser, ...globals.node },
      parserOptions: { parser: tseslint.parser, extraFileExtensions: ['.vue'] },
    },
    rules: {
      'vue/multi-word-component-names': 'off',
      'vue/no-v-html': 'off',
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
    },
  },
  {
    files: ['src/**/*.spec.ts', 'tests/**/*.ts'],
    languageOptions: { globals: { ...globals.browser, ...globals.node } },
  },
  {
    files: ['scripts/**/*.mjs'],
    languageOptions: { globals: globals.node },
  },
  prettier,
)
