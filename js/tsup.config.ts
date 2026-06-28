import { defineConfig } from "tsup";

export default defineConfig({
  entry: ["src/**/*.ts"],
  format: ["esm", "cjs"],
  dts: {
    resolve: true,
    compilerOptions: {
      types: ["node"],
      ignoreDeprecations: "6.0",
    },
  },
  tsconfig: "tsconfig.json",
  outDir: "dist",
  clean: true,
  sourcemap: false,
  target: "node20",
  platform: "node",
  bundle: true,
  splitting: false,
  outExtension({ format }) {
    return {
      js: format === "cjs" ? ".cjs" : ".js",
    };
  },
});
