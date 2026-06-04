/**
 * App (004-R1→R4) — the dashboard shell. Owns the ONE piece of cross-component state,
 * `selectedNpdid`: the map (R1) and the field list raise it, the detail panel (R2/R3/R4) consumes it.
 *
 * Selection has two routes (plan §3, accepted open-q): clicking a map polygon (primary), and a field
 * LIST beside the map (the accessible fallback). The list is what makes a NULL-geometry field —
 * which has no map polygon — still selectable (R1). To keep selection unambiguous, the list shows
 * the fields that are NOT drawn on the map (the geometry-less ones); every other field is reached by
 * its polygon. The selected field's identity is resolved from the field list and handed to the panel.
 */
import { useEffect, useMemo, useState } from "react";

import type { Field, NcsApiClient } from "./api/contracts";
import { FieldDetailPanel } from "./components/FieldDetailPanel";
import { FieldMap } from "./components/FieldMap";

interface AppProps {
  client: NcsApiClient;
}

export default function App({ client }: AppProps) {
  const [selectedNpdid, setSelectedNpdid] = useState<number | null>(null);
  const [fields, setFields] = useState<Field[]>([]);

  // The field list (R1 list + the source of the selected field's identity for the panel).
  useEffect(() => {
    let cancelled = false;
    void client.listFields().then((response) => {
      if (!cancelled) {
        setFields(response.fields);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [client]);

  const selectedField = useMemo(
    () => fields.find((f) => f.field_npdid === selectedNpdid) ?? null,
    [fields, selectedNpdid],
  );

  // Fields with NO outline geometry have no map polygon — surface them in the list so they stay
  // selectable (R1). Map-drawable fields are reached by clicking their polygon, so the list need
  // not repeat them (this also keeps each field's name to a single selection control).
  const listOnlyFields = useMemo(
    () => fields.filter((f) => f.geometry_wkt === null),
    [fields],
  );

  return (
    <div className="app">
      <header className="app__header">
        <h1>NCS Production Insights</h1>
      </header>

      <main className="app__main">
        <div className="app__sidebar">
          <div className="app__map" aria-label="Field map">
            <FieldMap
              client={client}
              selectedNpdid={selectedNpdid}
              onSelect={setSelectedNpdid}
            />
          </div>

          {listOnlyFields.length > 0 ? (
            <nav className="app__field-list" aria-label="Fields without map geometry">
              <h2 className="app__field-list-title">Fields without a map outline</h2>
              <ul>
                {listOnlyFields.map((field) => (
                  <li key={field.field_npdid}>
                    <button
                      type="button"
                      className="app__field-list-item"
                      aria-pressed={field.field_npdid === selectedNpdid}
                      onClick={() => setSelectedNpdid(field.field_npdid)}
                    >
                      {field.field_name}
                    </button>
                  </li>
                ))}
              </ul>
            </nav>
          ) : null}
        </div>

        <FieldDetailPanel client={client} field={selectedField} />
      </main>
    </div>
  );
}
