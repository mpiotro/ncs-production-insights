/**
 * Unit tests (developer-owned, principle 4) for FieldMap (004-R1).
 * Verifies: only features WITH geometry are drawn; a free, no-token OSM tile URL + attribution are
 * used; a feature click raises onSelect(field_npdid). react-leaflet is mocked inline (the
 * developer's own stand-in, separate from the acceptance harness).
 */
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Inline react-leaflet stand-in: surfaces the tile url/attribution and one clickable button per
// feature wired to eventHandlers.click with the Leaflet-shaped { target: { feature } } payload.
vi.mock("react-leaflet", () => {
  interface Feature {
    properties: { field_npdid: number; field_name: string };
  }
  return {
    MapContainer: ({ children }: { children?: React.ReactNode }) => (
      <div data-testid="map-container">{children}</div>
    ),
    TileLayer: ({ url, attribution }: { url?: string; attribution?: string }) => (
      <div data-testid="tile-layer" data-tile-url={url ?? ""} data-tile-attribution={attribution ?? ""} />
    ),
    GeoJSON: ({
      data,
      eventHandlers,
    }: {
      data?: { features?: Feature[] };
      eventHandlers?: { click?: (e: { target: { feature: Feature } }) => void };
    }) => (
      <div data-testid="geojson-layer">
        {(data?.features ?? []).map((feature, i) => (
          <button
            key={i}
            type="button"
            data-testid="geojson-feature"
            data-field-npdid={String(feature.properties.field_npdid)}
            onClick={() => eventHandlers?.click?.({ target: { feature } })}
          >
            {feature.properties.field_name}
          </button>
        ))}
      </div>
    ),
  };
});

import { FieldMap } from "./FieldMap";
import type { FieldFeatureCollection, NcsApiClient } from "../api/contracts";

const GEOJSON: FieldFeatureCollection = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      geometry: { type: "Polygon", coordinates: [] },
      properties: { field_npdid: 11, field_name: "ALPHA" },
    },
    {
      type: "Feature",
      geometry: null,
      properties: { field_npdid: 12, field_name: "NOGEOM" },
    },
  ],
};

function client(): NcsApiClient {
  return {
    listFields: vi.fn(),
    getField: vi.fn(),
    getProduction: vi.fn(),
    getForecast: vi.fn(),
    getFieldsGeoJson: vi.fn(async () => GEOJSON),
  } as NcsApiClient;
}

describe("FieldMap", () => {
  it("draws only the features that HAVE geometry (null-geometry field is not a polygon)", async () => {
    render(<FieldMap client={client()} selectedNpdid={null} onSelect={vi.fn()} />);

    const features = await screen.findAllByTestId("geojson-feature");
    expect(features).toHaveLength(1);
    expect(features[0].getAttribute("data-field-npdid")).toBe("11");
  });

  it("uses a free, no-token OSM tile URL with attribution", async () => {
    render(<FieldMap client={client()} selectedNpdid={null} onSelect={vi.fn()} />);

    const tile = await screen.findByTestId("tile-layer");
    const url = tile.getAttribute("data-tile-url") ?? "";
    expect(url).toMatch(/\{z\}\/\{x\}\/\{y\}/);
    expect(url.toLowerCase()).not.toMatch(/access[_-]?token|api[_-]?key|apikey|[?&]key=/);
    expect(tile.getAttribute("data-tile-attribution") ?? "").not.toHaveLength(0);
  });

  it("raises onSelect(field_npdid) when a feature is clicked", async () => {
    const onSelect = vi.fn();
    render(<FieldMap client={client()} selectedNpdid={null} onSelect={onSelect} />);

    const feature = (await screen.findAllByTestId("geojson-feature"))[0];
    await userEvent.click(feature);

    expect(onSelect).toHaveBeenCalledWith(11);
  });
});
