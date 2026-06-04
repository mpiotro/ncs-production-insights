/**
 * Unit tests (developer-owned, principle 4) for the shipping dev-mode mock client (004-R5/R4).
 * The dev mock ships in the bundle (powers `npm run dev` against VITE_API_SOURCE=mock), so it is
 * covered here: every method resolves its fixture, unknown NPDIDs reject, and the insufficient-
 * history field resolves the typed ForecastNotAvailable VALUE (R4) rather than throwing.
 */
import { describe, expect, it } from "vitest";

import { createMockClient } from "./mockClient";
import { FORECAST_NOT_AVAILABLE } from "./contracts";
import {
  DEV_NPDID_CREDIBLE,
  DEV_NPDID_LOW_CONFIDENCE,
  DEV_NPDID_NO_FORECAST,
  DEV_NPDID_NULL_GEOMETRY,
} from "./fixtures";

describe("dev mockClient", () => {
  it("listFields returns at least one field", async () => {
    const client = createMockClient();
    const list = await client.listFields();
    expect(list.count).toBe(list.fields.length);
    expect(list.fields.length).toBeGreaterThanOrEqual(1);
  });

  it("getFieldsGeoJson keeps the null-geometry field as a null-geometry feature", async () => {
    const client = createMockClient();
    const geojson = await client.getFieldsGeoJson();
    const nullFeature = geojson.features.find(
      (f) => f.properties.field_npdid === DEV_NPDID_NULL_GEOMETRY,
    );
    expect(nullFeature?.geometry).toBeNull();
  });

  it("getField resolves a known field and rejects an unknown NPDID", async () => {
    const client = createMockClient();
    await expect(client.getField(DEV_NPDID_CREDIBLE)).resolves.toMatchObject({
      field_npdid: DEV_NPDID_CREDIBLE,
    });
    await expect(client.getField(999999)).rejects.toThrow(/field_not_found/);
  });

  it("getProduction resolves a known field's history and rejects an unknown NPDID", async () => {
    const client = createMockClient();
    const history = await client.getProduction(DEV_NPDID_CREDIBLE);
    expect(history.production.length).toBeGreaterThan(0);
    await expect(client.getProduction(999999)).rejects.toThrow(/field_not_found/);
  });

  it("getForecast resolves a credible FieldForecast for the credible field", async () => {
    const client = createMockClient();
    const result = await client.getForecast(DEV_NPDID_CREDIBLE);
    expect("kind" in result).toBe(false);
    if (!("kind" in result)) {
      expect(result.credible).toBe(true);
      expect(result.points).toHaveLength(24);
    }
  });

  it("getForecast resolves a low-confidence FieldForecast for the low-confidence field", async () => {
    const client = createMockClient();
    const result = await client.getForecast(DEV_NPDID_LOW_CONFIDENCE);
    expect("kind" in result).toBe(false);
    if (!("kind" in result)) {
      expect(result.credible).toBe(false);
    }
  });

  it("getForecast resolves the typed ForecastNotAvailable VALUE for the short-history field (R4)", async () => {
    const client = createMockClient();
    const result = await client.getForecast(DEV_NPDID_NO_FORECAST);
    expect("kind" in result).toBe(true);
    if ("kind" in result) {
      expect(result.kind).toBe(FORECAST_NOT_AVAILABLE);
      expect(result.field_npdid).toBe(DEV_NPDID_NO_FORECAST);
    }
  });

  it("getForecast rejects an unknown NPDID (a genuine fault, not an outcome)", async () => {
    const client = createMockClient();
    await expect(client.getForecast(999999)).rejects.toThrow(/field_not_found/);
  });
});
