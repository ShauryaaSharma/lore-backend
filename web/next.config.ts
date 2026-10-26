import type { NextConfig } from "next";

// standalone: the Docker image ships only the traced server, not node_modules.
const config: NextConfig = { output: "standalone" };

export default config;
