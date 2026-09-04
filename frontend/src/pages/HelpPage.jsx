import { useQuery } from "@tanstack/react-query";
import Icon from "../components/ui/Icon.jsx";
import { apiFetch } from "../lib/api.js";

/** Localized thousand formatting (26,576). Returns "—" for missing values. */
function fmt(n) {
  return typeof n === "number" && Number.isFinite(n)
    ? n.toLocaleString("en-IN")
    : "—";
}

export default function HelpPage() {
  // Live canonical numbers (never hand-edit these — they change on every model
  // re-run; the sync button regenerates them). /api/dashboard is public.
  const { data: dash } = useQuery({
    queryKey: ["help", "dashboard-stats"],
    queryFn: () => apiFetch("/api/dashboard"),
    staleTime: 60_000,
  });

  const red = dash?.risk_level?.RED;
  const orange = dash?.risk_level?.ORANGE;
  const green = dash?.risk_level?.GREEN;
  const riskSummary = dash
    ? `${fmt(red)} / ${fmt(orange)} / ${fmt(green)}`
    : "— / — / —";

  return (
    <main className="flex-1 overflow-y-auto bg-phase-bg p-6">
      <div className="max-w-[800px] mx-auto">
        <div className="flex items-end justify-between border-b border-[#1E2330] pb-3 mb-6">
          <div>
            <h2 className="text-[20px] font-semibold text-phase-text">Help</h2>
            <p className="text-[13px] text-phase-text-secondary mt-1">
              VYOMA Operational Suite — user guide
            </p>
          </div>
        </div>

        <div className="space-y-6">
          {/* About */}
          <div className="bg-phase-elevated rounded-[4px] border border-[#1E2330] p-5">
            <h3 className="text-[14px] font-semibold text-phase-text mb-3 flex items-center gap-2">
              <Icon name="info" className="text-[16px] text-phase-text-secondary" />
              About VYOMA
            </h3>
            <p className="text-[13px] text-phase-text-secondary leading-relaxed">
              VYOMA is the NE India Hazard Red-Zone Platform — a GIS-based hazard
              susceptibility and relocation decision-support system built for the
              National Disaster Response Force (NDRF) and district administration
              under the Ministry of Home Affairs. It scores all 43,996 villages
              across the 7 North-Eastern states (Assam, Meghalaya, Manipur,
              Nagaland, Tripura, Mizoram, Arunachal Pradesh) for landslide and
              flood risk and recommends safe relocation destinations. Built for
              Smart India Hackathon 2026.
            </p>
          </div>

          {/* Underlying Model */}
          <div className="bg-phase-elevated rounded-[4px] border border-[#1E2330] p-5">
            <h3 className="text-[14px] font-semibold text-phase-text mb-3 flex items-center gap-2">
              <Icon name="psychology" className="text-[16px] text-phase-text-secondary" />
              Underlying Model
            </h3>
            <p className="text-[13px] text-phase-text-secondary leading-relaxed mb-3">
              Risk assessments come from a leakage-free XGBoost susceptibility
              classifier (v1.1-susceptibility, trained without historical-event
              proximity features and validated with leave-one-state-out spatial
              cross-validation). Every village receives:
            </p>
            <ul className="text-[13px] text-phase-text-secondary leading-relaxed mb-3 list-none space-y-1.5">
              <li className="flex items-start gap-2">
                <Icon name="check_circle" className="text-[15px] text-phase-text-secondary shrink-0 mt-0.5" />
                A continuous <span className="font-mono text-phase-text">risk score</span> (0.0–1.0)
              </li>
              <li className="flex items-start gap-2">
                <Icon name="check_circle" className="text-[15px] text-phase-text-secondary shrink-0 mt-0.5" />
                A <span className="font-mono text-phase-text">risk level</span> — RED / ORANGE / GREEN (current run: <span className="font-mono text-phase-text">{riskSummary}</span>)
              </li>
              <li className="flex items-start gap-2">
                <Icon name="check_circle" className="text-[15px] text-phase-text-secondary shrink-0 mt-0.5" />
                A <span className="font-mono text-phase-text">relocation priority</span> — IMMEDIATE / SHORT-TERM / MEDIUM-TERM / ROUTINE
              </li>
              <li className="flex items-start gap-2">
                <Icon name="check_circle" className="text-[15px] text-phase-text-secondary shrink-0 mt-0.5" />
                Separate <span className="font-mono text-phase-text">landslide</span> and <span className="font-mono text-phase-text">flood</span> risk scores (SHAP decomposition)
              </li>
              <li className="flex items-start gap-2">
                <Icon name="check_circle" className="text-[15px] text-phase-text-secondary shrink-0 mt-0.5" />
                Top contributing factors, a low-confidence flag, and a model-run timestamp + version
              </li>
            </ul>
            <div className="grid grid-cols-3 gap-3">
              <div className="bg-phase-card rounded-[4px] border border-[#1E2330] p-3 text-center">
                <span className="text-[10px] text-phase-text-secondary uppercase tracking-wider font-mono block mb-1">Villages</span>
                <span className="text-[16px] font-mono font-bold text-phase-text">{fmt(dash?.total_villages)}</span>
              </div>
              <div className="bg-phase-card rounded-[4px] border border-[#1E2330] p-3 text-center">
                <span className="text-[10px] text-phase-text-secondary uppercase tracking-wider font-mono block mb-1">RED / ORANGE / GREEN</span>
                <span className="text-[16px] font-mono font-bold text-phase-text">{riskSummary}</span>
              </div>
              <div className="bg-phase-card rounded-[4px] border border-[#1E2330] p-3 text-center">
                <span className="text-[10px] text-phase-text-secondary uppercase tracking-wider font-mono block mb-1">Relocation Sites</span>
                <span className="text-[16px] font-mono font-bold text-phase-text">{fmt(dash?.sites?.total)}</span>
              </div>
            </div>
            <p className="text-[12px] text-phase-text-secondary mt-3 leading-relaxed">
              Totals above are read live from the backend — they update
              automatically whenever the model is re-run (top-bar sync button).
            </p>
          </div>

          {/* Signing in */}
          <div className="bg-phase-elevated rounded-[4px] border border-[#1E2330] p-5">
            <h3 className="text-[14px] font-semibold text-phase-text mb-3 flex items-center gap-2">
              <Icon name="login" className="text-[16px] text-phase-text-secondary" />
              Signing in &amp; Accounts
            </h3>
            <p className="text-[13px] text-phase-text-secondary leading-relaxed mb-3">
              The platform requires an account. Unauthenticated visitors are
              redirected to the sign-in screen; after signing in you land on the
              Dashboard. Click <span className="font-mono text-phase-text">Logout</span> in
              the sidebar (it asks for confirmation first) to end the session.
            </p>
            <div className="bg-phase-card rounded-[4px] border border-[#1E2330] p-3 font-mono text-[12px] text-phase-text-secondary leading-relaxed">
              Demo account: admin@vyoma.in&nbsp;&nbsp;·&nbsp;&nbsp;password: admin123
            </div>
            <p className="text-[12px] text-phase-text-secondary mt-3 leading-relaxed">
              New accounts are created by the platform owner from the backend
              folder: <span className="font-mono">npm run create-user &lt;email&gt; &lt;password&gt; [name]</span>
            </p>
          </div>

          {/* Staying current */}
          <div className="bg-phase-elevated rounded-[4px] border border-[#1E2330] p-5">
            <h3 className="text-[14px] font-semibold text-phase-text mb-3 flex items-center gap-2">
              <Icon name="sync" className="text-[16px] text-phase-text-secondary" />
              Data Freshness &amp; the Sync Button
            </h3>
            <ul className="text-[13px] text-phase-text-secondary leading-relaxed list-none space-y-1.5">
              <li className="flex items-start gap-2">
                <Icon name="schedule" className="text-[15px] text-phase-text-secondary shrink-0 mt-0.5" />
                The chip in the Dashboard header shows when the model last ran — <span className="font-mono text-phase-text">Predicted &lt;date&gt; · &lt;version&gt;</span> — and updates automatically after a refresh.
              </li>
              <li className="flex items-start gap-2">
                <Icon name="sync" className="text-[15px] text-phase-text-secondary shrink-0 mt-0.5" />
                The top-bar <span className="font-mono text-phase-text">sync</span> button re-runs the full model pipeline (re-predict all villages, regenerate relocation plans, sites, exports and static bundles, reload the database). It takes roughly 5–15 minutes — you can keep using the app meanwhile; the button shows the current step.
              </li>
              <li className="flex items-start gap-2">
                <Icon name="bolt" className="text-[15px] text-phase-text-secondary shrink-0 mt-0.5" />
                Village and site data is served from versioned static bundles, so the first page load never touches the database and new model runs always reach your browser (a single reload is needed after a deployment that changes the frontend code itself).
              </li>
            </ul>
          </div>

          {/* Navigation Guide */}
          <div className="bg-phase-elevated rounded-[4px] border border-[#1E2330] p-5">
            <h3 className="text-[14px] font-semibold text-phase-text mb-3 flex items-center gap-2">
              <Icon name="menu_book" className="text-[16px] text-phase-text-secondary" />
              Navigation Guide
            </h3>
            <div className="space-y-3">
              {[
                { icon: "dashboard", label: "Dashboard", desc: "District-level overview: zone counts, hazard map, critical villages, relocation priority and site capacity" },
                { icon: "map", label: "Hazard Map", desc: "Interactive map with risk-colored village markers for every village, zoom-level clustering, and RED/ORANGE/GREEN filters" },
                { icon: "home_pin", label: "Villages", desc: "Searchable/filterable table of all 43,996 villages with risk profiles" },
                { icon: "priority_high", label: "Relocation Priority", desc: "Kanban board grouping villages by relocation urgency (IMMEDIATE → ROUTINE)" },
                { icon: "location_on", label: "Relocation Sites", desc: "Registered relocation sites with suitability, remaining capacity, and infrastructure status" },
                { icon: "analytics", label: "Analytics", desc: "Risk distribution, site capacity, and hazard-factor analysis across the dataset" },
              ].map((item) => (
                <div key={item.label} className="flex items-start gap-3">
                  <Icon name={item.icon} className="text-[18px] text-phase-text-secondary mt-0.5 shrink-0" />
                  <div>
                    <span className="text-[13px] text-phase-text font-medium">{item.label}</span>
                    <p className="text-[12px] text-phase-text-secondary">{item.desc}</p>
                  </div>
                </div>
              ))}
              <div className="flex items-start gap-3">
                <Icon name="home_work" className="text-[18px] text-phase-text-secondary mt-0.5 shrink-0" />
                <div>
                  <span className="text-[13px] text-phase-text font-medium">Village detail pages</span>
                  <p className="text-[12px] text-phase-text-secondary">
                    Every village page shows its risk assessment, top contributing factors, and the
                    <span className="font-mono"> relocation plan</span> card — the recommended safe destination,
                    the relocation distance in km, and the capacity fit (full / partial / minimal).
                  </p>
                </div>
              </div>
            </div>
            <p className="text-[12px] text-phase-text-secondary mt-4 leading-relaxed">
              Use the <span className="font-mono">State</span> / <span className="font-mono">District</span>
              selectors in the top bar to narrow every view to a region — filtering happens instantly
              in the browser over the full dataset.
            </p>
          </div>

          {/* Keyboard Shortcuts */}
          <div className="bg-phase-elevated rounded-[4px] border border-[#1E2330] p-5">
            <h3 className="text-[14px] font-semibold text-phase-text mb-3 flex items-center gap-2">
              <Icon name="keyboard" className="text-[16px] text-phase-text-secondary" />
              Keyboard Shortcuts
            </h3>
            <div className="space-y-2">
              {[
                { keys: "Scroll", action: "Zoom in/out on map" },
                { keys: "Click + Drag", action: "Pan map" },
                { keys: "Click marker", action: "Open village popup" },
              ].map((shortcut) => (
                <div key={shortcut.keys} className="flex items-center justify-between">
                  <span className="text-[12px] font-mono text-phase-text-secondary px-2 py-0.5 bg-phase-card rounded-[2px] border border-[#1E2330]">
                    {shortcut.keys}
                  </span>
                  <span className="text-[12px] text-phase-text-secondary">{shortcut.action}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
