/**
 * Shared jsdom-safe stand-ins for the heavy view libraries (plan/tasks open-q #1).
 *
 * `react-plotly.js` (canvas/WebGL) and `react-leaflet` (real DOM map) cannot render under
 * jsdom, and the acceptance suites are black-box at the *component contract* anyway — they
 * assert on the data/props the components hand to the chart and map, plus user-visible text.
 * So every suite replaces those two modules with the light stand-ins below.
 *
 * USAGE (hoisting-safe). `vi.mock(...)` is hoisted above imports, so a factory must not close
 * over a top-level binding. Each suite therefore does:
 *
 *     vi.mock("react-plotly.js", async () =>
 *       (await import("./harness/viewMocks")).reactPlotlyMock(),
 *     );
 *     vi.mock("react-leaflet", async () =>
 *       (await import("./harness/viewMocks")).reactLeafletMock(),
 *     );
 *
 * The dynamic `import()` inside the async factory is evaluated after hoisting, so this is safe.
 *
 * The stand-ins expose their inputs as DOM the tests can read:
 *  - Plotly  → a `data-testid="plotly-chart"` node with one `data-testid="plotly-trace"` child
 *              per trace, each carrying `data-trace-name`, `data-trace-mode`, `data-trace-dash`,
 *              `data-point-count`, and `data-trace-y` (the serialized value series). That makes
 *              "a history trace + a 24-point forecast trace, visually distinct" assertable from
 *              the `data` prop alone, and lets a test confirm a null oe month stays `null`, not
 *              0.0 (004-R2).
 *  - Leaflet → `MapContainer`/`TileLayer`/`GeoJSON` stand-ins. `TileLayer` exposes its `url` and
 *              `attribution` (so the free, no-token OSM tiles are inspectable — 004-R1). `GeoJSON`
 *              renders one clickable `data-testid="geojson-feature"` button PER FEATURE, wired to
 *              `eventHandlers.click` with that feature as the Leaflet-style `{ target: { feature } }`
 *              payload (so polygon-click selection is assertable — 004-R1).
 */
import React from "react";

// --- Plotly stand-in --------------------------------------------------------

/** The subset of a Plotly trace the chart hands us that the stand-in surfaces for assertions. */
interface PlotlyTrace {
  name?: string;
  mode?: string;
  x?: unknown[];
  y?: unknown[];
  line?: { dash?: string };
}

interface PlotlyProps {
  data?: PlotlyTrace[];
}

/**
 * Build the `react-plotly.js` mock module (default export `Plot`). Call inside a `vi.mock`
 * factory. Renders the `data` prop as inspectable DOM — never touches canvas.
 */
export function reactPlotlyMock(): { default: React.FC<PlotlyProps> } {
  const Plot: React.FC<PlotlyProps> = ({ data = [] }) =>
    React.createElement(
      "div",
      { "data-testid": "plotly-chart", "data-trace-count": String(data.length) },
      data.map((trace, i) =>
        React.createElement("div", {
          key: i,
          "data-testid": "plotly-trace",
          "data-trace-name": trace.name ?? "",
          "data-trace-mode": trace.mode ?? "",
          "data-trace-dash": trace.line?.dash ?? "",
          // Point count is taken from y (the value series); a `null` y entry still counts as a
          // plotted slot (it is a gap, not a dropped point) — see fixtures' null-oe month (R2).
          "data-point-count": String((trace.y ?? trace.x ?? []).length),
          // Serialized y so a test can confirm a null oe month survives as `null`, not 0.0 (R2).
          // JSON.stringify maps a JS `null` value to the literal "null".
          "data-trace-y": JSON.stringify(trace.y ?? []),
        }),
      ),
    );
  Plot.displayName = "MockPlot";
  return { default: Plot };
}

// --- Leaflet stand-ins ------------------------------------------------------

interface MapContainerProps {
  children?: React.ReactNode;
}

interface TileLayerProps {
  url?: string;
  attribution?: string;
}

/** Minimal GeoJSON Feature shape the map renders (matches FieldFeature from contracts). */
interface GeoJsonFeatureLike {
  type: "Feature";
  geometry: unknown;
  properties: { field_npdid: number; field_name: string };
}

interface GeoJsonProps {
  data?: { features?: GeoJsonFeatureLike[] };
  eventHandlers?: {
    click?: (event: { target: { feature: GeoJsonFeatureLike } }) => void;
  };
}

/**
 * Build the `react-leaflet` mock module (`MapContainer`, `TileLayer`, `GeoJSON`). Call inside a
 * `vi.mock` factory. The `GeoJSON` stand-in renders one clickable button per feature so a click
 * fires `eventHandlers.click` with the Leaflet-shaped `{ target: { feature } }` payload.
 */
export function reactLeafletMock(): {
  MapContainer: React.FC<MapContainerProps>;
  TileLayer: React.FC<TileLayerProps>;
  GeoJSON: React.FC<GeoJsonProps>;
} {
  const MapContainer: React.FC<MapContainerProps> = ({ children }) =>
    React.createElement("div", { "data-testid": "map-container" }, children);
  MapContainer.displayName = "MockMapContainer";

  const TileLayer: React.FC<TileLayerProps> = ({ url, attribution }) =>
    React.createElement("div", {
      "data-testid": "tile-layer",
      "data-tile-url": url ?? "",
      "data-tile-attribution": attribution ?? "",
    });
  TileLayer.displayName = "MockTileLayer";

  const GeoJSON: React.FC<GeoJsonProps> = ({ data, eventHandlers }) => {
    const features = data?.features ?? [];
    return React.createElement(
      "div",
      { "data-testid": "geojson-layer", "data-feature-count": String(features.length) },
      features.map((feature, i) =>
        React.createElement(
          "button",
          {
            key: i,
            type: "button",
            "data-testid": "geojson-feature",
            "data-field-npdid": String(feature.properties.field_npdid),
            onClick: () => eventHandlers?.click?.({ target: { feature } }),
          },
          feature.properties.field_name,
        ),
      ),
    );
  };
  GeoJSON.displayName = "MockGeoJSON";

  return { MapContainer, TileLayer, GeoJSON };
}
