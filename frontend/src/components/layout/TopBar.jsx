/**
 * Top navigation bar.
 * Contains cascading state/district selectors, hamburger menu (mobile), and trailing action icons.
 */
import { useState, useRef, useEffect } from "react";
import { useLocation } from "react-router-dom";
import Icon from "../ui/Icon.jsx";
import { useSelection } from "../../context/SelectionContext.jsx";
import { useRefresh } from "../../context/RefreshContext.jsx";
import { useAuth } from "../../context/AuthContext.jsx";

const REFRESH_CONFIRM =
  "Re-run the model now?\n\n" +
  "This re-predicts all 43,996 villages, regenerates the relocation sites, " +
  "exports and static bundles, then reloads the database. " +
  "It takes about 5-15 minutes — you can keep using the app meanwhile.\n\n" +
  "Continue?";

/** Initials chip fallback when the signed-in user has no avatar URL. */
function initialsOf(name) {
  return (name || "U")
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0].toUpperCase())
    .join("");
}

function Dropdown({ label, value, options, onChange, placeholder, disabled = false }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    function handleClick(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  // Close if it becomes disabled while open
  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);

  return (
    <div ref={ref} className="relative">
      <button
        disabled={disabled}
        onClick={() => setOpen(!open)}
        className={`flex items-center gap-2 bg-surface-base border border-border-subtle rounded-[6px] px-3 py-1.5 transition-colors min-w-[140px] ${
          disabled
            ? "opacity-50 cursor-not-allowed"
            : "hover:bg-surface-container cursor-pointer"
        }`}
      >
        <span className={`font-label-md text-label-md ${value ? "text-on-surface" : "text-on-surface-variant"}`}>
          {label}: {value || placeholder}
        </span>
        <Icon
          name="arrow_drop_down"
          className={`text-[16px] text-on-surface-variant transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>
      {open && (
        <div className="absolute top-full left-0 mt-1 w-full min-w-[180px] bg-surface-container border border-border-subtle rounded-[4px] shadow-xl z-50 max-h-[240px] overflow-y-auto">
          <button
            onClick={() => { onChange(null); setOpen(false); }}
            className={`w-full text-left px-3 py-2 text-[13px] font-mono hover:bg-surface-variant transition-colors ${
              value === null ? "text-on-surface bg-surface-variant" : "text-on-surface-variant"
            }`}
          >
            {placeholder}
          </button>
          {options.map((opt) => (
            <button
              key={opt}
              onClick={() => { onChange(opt); setOpen(false); }}
              className={`w-full text-left px-3 py-2 text-[13px] font-mono hover:bg-surface-variant transition-colors ${
                value === opt ? "text-on-surface bg-surface-variant" : "text-on-surface-variant"
              }`}
            >
              {opt}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function TopBar({ onMenuToggle }) {
  const {
    selectedState,
    selectedDistrict,
    states,
    districts,
    districtsLoading,
    selectState,
    selectDistrict,
  } = useSelection();
  const { refreshing, refreshAll, refreshError, refreshStep } = useRefresh();
  const { user } = useAuth();

  // The Dashboard (“/”) is a NATIONAL overview by design — its numbers cover all
  // 43,996 villages, so the State/District filters are hidden there. They remain
  // available on every region-filterable page (map, villages, priority, …).
  const location = useLocation();
  const isDashboard = location.pathname === "/dashboard";

  // Surface job failures (backend down, a pipeline step failed, …).
  useEffect(() => {
    if (refreshError) window.alert(`Model refresh failed:\n\n${refreshError}`);
  }, [refreshError]);

  const districtPlaceholder =
    !selectedState
      ? "Select State first"
      : districtsLoading
        ? "Loading districts…"
        : "Select District";

  return (
    <header className="bg-surface dark:bg-surface font-body-md text-body-md flex justify-between items-center w-full px-gutter h-16 border-b border-border-subtle z-30">
      {/* Left: Hamburger (mobile) + Selectors */}
      <div className="flex items-center gap-4">
        {/* Hamburger — visible only on mobile */}
        <button
          onClick={onMenuToggle}
          className="md:hidden text-on-surface-variant hover:text-primary transition-colors p-1 rounded-[4px] hover:bg-surface-variant"
        >
          <Icon name="menu" />
        </button>

        {!isDashboard && (
          <div className="flex items-center gap-4">
            <Dropdown
              label="State"
              value={selectedState}
              options={states}
              onChange={selectState}
              placeholder="Select State"
            />
            <Dropdown
              label="District"
              value={selectedDistrict}
              options={districts}
              onChange={selectDistrict}
              placeholder={districtPlaceholder}
              disabled={!selectedState || districtsLoading}
            />
          </div>
        )}
      </div>

      {/* Right: Refresh + Action icons + Avatar */}
      <div className="flex items-center gap-4">
        <button
          onClick={() => {
            if (window.confirm(REFRESH_CONFIRM)) refreshAll();
          }}
          disabled={refreshing}
          title={
            refreshing
              ? `Re-running the model: ${refreshStep?.message || "working…"} — this takes several minutes`
              : "Re-run the model: re-predict all villages, regenerate exports, reload the database (~5-15 min)"
          }
          className="text-on-surface-variant hover:text-primary transition-colors p-1 rounded-[4px] hover:bg-surface-variant disabled:opacity-60 disabled:cursor-wait"
        >
          <Icon name="sync" className={refreshing ? "animate-spin text-primary" : ""} />
        </button>
        {/* Signed-in user — initials chip (name/role in the tooltip) */}
        <div
          className="w-8 h-8 rounded-full bg-primary flex items-center justify-center ml-2 cursor-pointer select-none"
          title={`${user?.name || "User"}${user?.email ? ` · ${user.email}` : ""}`}
        >
          <span className="text-surface-lowest font-label-sm text-label-sm font-bold">
            {initialsOf(user?.name)}
          </span>
        </div>
      </div>
    </header>
  );
}
