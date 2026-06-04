/**
 * Type-conformance test (developer-owned, 004-R5 faithfulness, principle 9).
 *
 * The friendly snake_case aliases in `contracts.ts` are hand-restated, but they MUST stay faithful
 * to 003's OpenAPI. `schema.gen.ts` is generated from a committed snapshot of `/openapi.json`
 * (`npm run gen:api`). These `expectTypeOf` assertions assert each friendly alias is assignable to
 * the corresponding generated schema type — so if 003's contract drifts and the snapshot is
 * regenerated, an incompatible alias becomes a COMPILE error (caught by `tsc --noEmit` in
 * `npm run typecheck` / `npm run build`, the CI gate in T11), not silent rot.
 *
 * The assertions are type-level; the runtime body is a trivially-passing assertion so the suite
 * also gives R5 a citing, executable test (principle 9).
 */
import { describe, expectTypeOf, it } from "vitest";

import type {
  ErrorCode,
  ErrorResponse,
  Field,
  FieldFeature,
  FieldFeatureCollection,
  FieldForecast,
  FieldListResponse,
  FieldProperties,
  ForecastMethod,
  ForecastPoint,
  ForecastTarget,
  MonthlyProduction,
  ProductionHistoryResponse,
} from "./contracts";
import type { components } from "./schema.gen";

type Schemas = components["schemas"];

describe("004-R5 — friendly contracts.ts aliases stay assignable to schema.gen.ts (OpenAPI faithfulness)", () => {
  it("each friendly alias conforms to its generated schema type", () => {
    // Frozen 001 models.
    expectTypeOf<MonthlyProduction>().toMatchTypeOf<Schemas["MonthlyProduction"]>();
    expectTypeOf<Field>().toMatchTypeOf<Schemas["Field"]>();

    // Frozen 002 forecast models. The closed unions must equal the generated members exactly.
    expectTypeOf<ForecastMethod>().toEqualTypeOf<Schemas["ForecastMethod"]>();
    expectTypeOf<ForecastTarget>().toEqualTypeOf<Schemas["ForecastTarget"]>();
    expectTypeOf<ForecastPoint>().toMatchTypeOf<Schemas["ForecastPoint"]>();
    expectTypeOf<FieldForecast>().toMatchTypeOf<Schemas["FieldForecast"]>();

    // 003 transport envelopes.
    expectTypeOf<FieldListResponse>().toMatchTypeOf<Schemas["FieldListResponse"]>();
    expectTypeOf<ProductionHistoryResponse>().toMatchTypeOf<
      Schemas["ProductionHistoryResponse"]
    >();

    // GeoJSON FeatureCollection.
    expectTypeOf<FieldProperties>().toMatchTypeOf<Schemas["FieldProperties"]>();
    expectTypeOf<FieldFeature>().toMatchTypeOf<Schemas["FieldFeature"]>();
    expectTypeOf<FieldFeatureCollection>().toMatchTypeOf<Schemas["FieldFeatureCollection"]>();

    // Typed error body — both 404s tell apart via `code`.
    expectTypeOf<ErrorCode>().toEqualTypeOf<Schemas["ErrorCode"]>();
    expectTypeOf<ErrorResponse>().toMatchTypeOf<Schemas["ErrorResponse"]>();

    // A trivially-true runtime assertion keeps this an executable, citing test (principle 9).
    expectTypeOf<Field>().toBeObject();
  });
});
