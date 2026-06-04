/**
 * 004-R1 — The dashboard SHALL render the NCS fields on a Leaflet map as GeoJSON polygons (from
 * the 003 geometry endpoint), using free tiles with no API token; fields are selectable.
 *
 * Black-box (principle 4): real components, injected mock NcsApiClient, heavy view libs mocked to
 * the shared stand-ins (test/acceptance/harness/viewMocks). We assert on user-visible output and
 * the data handed to the map — never on internals.
 *
 * RED until the developer builds `src/App` and `src/components/FieldMap` (T10).
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Hoisting-safe: the factory dynamically imports the harness AFTER vi.mock hoisting (see viewMocks).
vi.mock("react-leaflet", async () => (await import("./harness/viewMocks")).reactLeafletMock());
vi.mock("react-plotly.js", async () => (await import("./harness/viewMocks")).reactPlotlyMock());

import App from "../../src/App";
import { FieldMap } from "../../src/components/FieldMap";
import { createMockClient } from "./harness/mockClient";
import {
  FEATURES_WITH_GEOMETRY,
  NPDID_CREDIBLE,
  NPDID_NULL_GEOMETRY,
} from "./harness/fixtures";

let client: ReturnType<typeof createMockClient>;

beforeEach(() => {
  client = createMockClient();
});

describe("004-R1 — NCS fields on a Leaflet map (GeoJSON polygons, free tiles, selectable)", () => {
  it("004-R1: renders one map feature per field that HAS geometry, from the geometry endpoint", async () => {
    render(<FieldMap client={client} selectedNpdid={null} onSelect={vi.fn()} />);

    // The map source is the 003 GeoJSON endpoint.
    await vi.waitFor(() => expect(client.getFieldsGeoJson).toHaveBeenCalled());

    // One clickable polygon per field WITH geometry. The null-geometry field has no outline and
    // must NOT be rendered as a map polygon (it would have no coordinates for Leaflet); it is
    // reachable via the field-list fallback instead (asserted below).
    const features = await screen.findAllByTestId("geojson-feature");
    expect(features).toHaveLength(FEATURES_WITH_GEOMETRY);
    expect(FEATURES_WITH_GEOMETRY).toBe(3);
  });

  it("004-R1: draws the GeoJSON over a FREE, no-token tile layer (OSM-style url, attribution)", async () => {
    render(<FieldMap client={client} selectedNpdid={null} onSelect={vi.fn()} />);

    const tile = await screen.findByTestId("tile-layer");
    const url = tile.getAttribute("data-tile-url") ?? "";

    // A real raster tile URL with the standard {z}/{x}/{y} template …
    expect(url).toMatch(/\{z\}\/\{x\}\/\{y\}/);
    // … and crucially NO API token / access key of any kind (R1 + scope: no paid tiles/tokens).
    expect(url.toLowerCase()).not.toMatch(/access[_-]?token|api[_-]?key|apikey|[?&]key=/);
    // Attribution is present (OSM usage policy).
    expect(tile.getAttribute("data-tile-attribution") ?? "").not.toHaveLength(0);
  });

  it("004-R1: clicking a map feature selects that field_npdid (onSelect fires with the npdid)", async () => {
    const onSelect = vi.fn();
    render(<FieldMap client={client} selectedNpdid={null} onSelect={onSelect} />);

    const features = await screen.findAllByTestId("geojson-feature");
    const snorre = features.find(
      (el) => el.getAttribute("data-field-npdid") === String(NPDID_CREDIBLE),
    );
    expect(snorre).toBeDefined();

    await userEvent.click(snorre!);

    expect(onSelect).toHaveBeenCalledWith(NPDID_CREDIBLE);
  });

  it("004-R1: clicking a field on the map selects it end-to-end (its detail appears in <App>)", async () => {
    render(<App client={client} />);

    const features = await screen.findAllByTestId("geojson-feature");
    const snorre = features.find(
      (el) => el.getAttribute("data-field-npdid") === String(NPDID_CREDIBLE),
    );
    await userEvent.click(snorre!);

    // Selecting the field drives the detail panel to fetch + show that field (the map⇄chart join
    // key is field_npdid). The proof is SCOPED to the detail region: the selected field's name
    // appearing as the detail heading — not the always-present map polygon button — is what the
    // selection adds (the demo's visible surface).
    const detail = screen.getByLabelText("Field detail");
    expect(await within(detail).findByRole("heading", { name: /SNORRE/i })).toBeInTheDocument();
    await vi.waitFor(() =>
      expect(client.getProduction).toHaveBeenCalledWith(NPDID_CREDIBLE),
    );
  });

  it("004-R1: a null-geometry field (no polygon) is still selectable via the field list", async () => {
    render(<App client={client} />);

    // The null-geometry field never appears as a map polygon …
    const features = await screen.findAllByTestId("geojson-feature");
    expect(
      features.some(
        (el) => el.getAttribute("data-field-npdid") === String(NPDID_NULL_GEOMETRY),
      ),
    ).toBe(false);

    // … but the list fallback (plan §3 / open-q: list beside the map) must let the user select it.
    // With no map polygon for it, the only clickable "NULLGEOM" control is the list entry.
    const listEntry = await screen.findByRole("button", { name: /NULLGEOM/i });
    await userEvent.click(listEntry);

    await vi.waitFor(() =>
      expect(client.getProduction).toHaveBeenCalledWith(NPDID_NULL_GEOMETRY),
    );
    // And its detail renders, proving selection succeeded for a null-geometry field. Scope the
    // name assertion to the detail region (the selected field surfaces there as the heading), so
    // it proves selection populated the detail — not just the list button that was always present.
    const detail = screen.getByLabelText("Field detail");
    const charts = await screen.findAllByTestId("plotly-chart");
    expect(charts.length).toBeGreaterThanOrEqual(1);
    expect(await within(detail).findByRole("heading", { name: /NULLGEOM/i })).toBeInTheDocument();
  });
});
