import { createContext, useContext, useEffect, useRef, useState } from "react";
import { apiFetch } from "../lib/api.js";

/**
 * SelectionContext — manages the global State/District selection.
 * All pages consume this to filter their data by the selected region.
 *
 * The 7 North-Eastern states are fixed (they match the model's coverage).
 * Districts are loaded live from GET /api/villages/districts?state=… so the
 * cascading dropdown reflects the real Census district names in the data —
 * not a hardcoded placeholder list.
 */

const STATES = [
  "Arunachal Pradesh",
  "Assam",
  "Manipur",
  "Meghalaya",
  "Mizoram",
  "Nagaland",
  "Tripura",
];

const SelectionContext = createContext(null);

export function SelectionProvider({ children }) {
  const [selectedState, setSelectedState] = useState(null);
  const [selectedDistrict, setSelectedDistrict] = useState(null);
  const [districts, setDistricts] = useState([]);
  const [districtsLoading, setDistrictsLoading] = useState(false);
  // Guards against stale responses when the user switches states quickly.
  const fetchToken = useRef(0);

  // Load districts whenever a state is selected (or cleared).
  useEffect(() => {
    const token = ++fetchToken.current;
    if (!selectedState) {
      setDistricts([]);
      setDistrictsLoading(false);
      return;
    }
    setDistrictsLoading(true);
    apiFetch(`/api/villages/districts?state=${encodeURIComponent(selectedState)}`)
      .then((list) => {
        if (token !== fetchToken.current) return; // stale response
        setDistricts(Array.isArray(list) ? list : []);
        setDistrictsLoading(false);
      })
      .catch(() => {
        if (token !== fetchToken.current) return;
        setDistricts([]);
        setDistrictsLoading(false);
      });
  }, [selectedState]);

  function selectState(state) {
    setSelectedState(state);
    setSelectedDistrict(null); // reset district when state changes
  }

  function selectDistrict(district) {
    setSelectedDistrict(district);
  }

  const value = {
    selectedState,
    selectedDistrict,
    states: STATES,
    districts,
    districtsLoading,
    selectState,
    selectDistrict,
    /** Convenience: is the current filter actually applied? */
    hasFilter: selectedState !== null || selectedDistrict !== null,
  };

  return (
    <SelectionContext.Provider value={value}>
      {children}
    </SelectionContext.Provider>
  );
}

export function useSelection() {
  const ctx = useContext(SelectionContext);
  if (!ctx) throw new Error("useSelection must be used within SelectionProvider");
  return ctx;
}
