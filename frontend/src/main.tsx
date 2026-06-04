import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

// Minimal React root for 004-T1 scaffolding. The real <App/> (map + detail panel,
// client wiring via selectClient) is built in 004-T10; this placeholder keeps the
// entrypoint valid and the build green until then.
const rootElement = document.getElementById("root");
if (rootElement) {
  createRoot(rootElement).render(
    <StrictMode>
      <h1>NCS Production Insights</h1>
    </StrictMode>,
  );
}
