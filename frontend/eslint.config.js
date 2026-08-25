import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    rules: {
      // shadcn/ui 组件惯例：同一文件导出组件与 variants 常量，fast-refresh 规则降级为 warn
      'react-refresh/only-export-components': 'warn',
      // sidebar skeleton 在 useMemo 中使用 Math.random 生成一次性随机宽度，属稳定模式，降级为 warn
      'react-hooks/purity': 'warn',
    },
  },
])
