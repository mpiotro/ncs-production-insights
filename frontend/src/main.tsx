/**
 * React root (004-T10). Reads config from `import.meta.env` (config.ts), picks the client
 * (real http vs in-memory mock) by config ALONE via selectClient (R5), and mounts <App/>.
 * Swapping mock <-> live 003 is a `VITE_API_SOURCE` change — no code change here.
 */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import { selectClient } from "./api/selectClient";
import { readConfig } from "./config";

const client = selectClient(readConfig());

const rootElement = document.getElementById("root");
if (rootElement) {
  createRoot(rootElement).render(
    <StrictMode>
      <App client={client} />
    </StrictMode>,
  );
}
