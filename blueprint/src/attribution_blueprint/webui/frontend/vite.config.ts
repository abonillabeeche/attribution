// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: LicenseRef-NvidiaProprietary

/// <reference types="vitest/config" />
import path from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  base: '/',
  build: {
    // Repo-local build target: the package's served static dir.
    // Docker overrides this with `vite build --outDir dist` in its Node stage.
    outDir: '../static',
    emptyOutDir: true,
  },
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    // Vitest blanks every stylesheet import, `?raw` included. The design-token
    // guard in application-components.test.tsx reads globals.css as text.
    css: { include: [/\/src\/styles\/globals\.css\?raw$/] },
  },
})
