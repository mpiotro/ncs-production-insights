/**
 * FieldMap (004-R1) — the NCS fields as GeoJSON polygons on a Leaflet map, over FREE tiles.
 *
 * Loads the map source from 003's `/fields.geojson` (via the injected client) and draws a `GeoJSON`
 * layer over an OpenStreetMap `TileLayer` — free raster tiles, NO API token (R1 + scope). Only
 * features that HAVE geometry are drawn (a null-geometry field has no polygon; it stays selectable
 * via the field list in <App>). Clicking a feature raises `onSelect(field_npdid)` — the map⇄chart
 * join key (R1→R2). react-leaflet is the heavy view lib (mocked to stand-ins in the acceptance
 * suites); we only hand it the layer data, tile config, and a click handler.
 */
import type { GeoJsonObject } from "geojson";
import type { LeafletMouseEvent } from "leaflet";
import { useEffect, useState } from "react";
import { GeoJSON, MapContainer, TileLayer } from "react-leaflet";

import type { FieldFeature, FieldFeatureCollection, NcsApiClient } from "../api/contracts";

interface FieldMapProps {
  client: NcsApiClient;
  /** The currently selected field (kept for future styling/highlight; selection lives in <App>). */
  selectedNpdid: number | null;
  /** Raised with a field's NPDID when its polygon is clicked. */
  onSelect: (npdid: number) => void;
}

/** Free, no-token OpenStreetMap raster tiles (R1). The {z}/{x}/{y} template + attribution are required. */
const OSM_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const OSM_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

/** Center/zoom over the central North Sea so the NCS fields are in view on first paint. */
const INITIAL_CENTER: [number, number] = [60.0, 3.0];
const INITIAL_ZOOM = 5;

/** A feature has a drawable outline iff its geometry is non-null. */
function hasGeometry(feature: FieldFeature): boolean {
  return feature.geometry !== null;
}

/**
 * Extract the clicked field's feature from a Leaflet click event. On a real GeoJSON layer the
 * feature is on the clicked sublayer (`event.sourceTarget.feature` / `event.layer.feature`); the
 * acceptance stand-in passes it as `event.target.feature`. We read all three defensively.
 */
function featureFromEvent(event: LeafletMouseEvent): FieldFeature | undefined {
  const candidate = event as unknown as {
    target?: { feature?: FieldFeature };
    sourceTarget?: { feature?: FieldFeature };
    layer?: { feature?: FieldFeature };
  };
  return (
    candidate.sourceTarget?.feature ?? candidate.layer?.feature ?? candidate.target?.feature
  );
}

export function FieldMap({ client, selectedNpdid, onSelect }: FieldMapProps) {
  const [collection, setCollection] = useState<FieldFeatureCollection | null>(null);

  useEffect(() => {
    let cancelled = false;
    void client.getFieldsGeoJson().then((data) => {
      if (!cancelled) {
        setCollection(data);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [client]);

  // Only the features WITH geometry become map polygons; null-geometry fields have none (R1).
  const drawable: FieldFeatureCollection | null =
    collection === null
      ? null
      : { type: "FeatureCollection", features: collection.features.filter(hasGeometry) };

  return (
    <MapContainer
      center={INITIAL_CENTER}
      zoom={INITIAL_ZOOM}
      style={{ height: "100%", width: "100%" }}
      data-selected-npdid={selectedNpdid ?? ""}
    >
      <TileLayer url={OSM_TILE_URL} attribution={OSM_ATTRIBUTION} />
      {drawable ? (
        <GeoJSON
          // `key` forces a fresh layer if the data changes (Leaflet caches the layer otherwise).
          key={drawable.features.length}
          data={drawable as unknown as GeoJsonObject}
          eventHandlers={{
            click: (event: LeafletMouseEvent) => {
              const feature = featureFromEvent(event);
              if (feature) {
                onSelect(feature.properties.field_npdid);
              }
            },
          }}
        />
      ) : null}
    </MapContainer>
  );
}
