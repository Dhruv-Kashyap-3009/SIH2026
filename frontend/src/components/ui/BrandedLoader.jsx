/**
 * Branded loading block — spinning ring around the VYOMA mark + animated
 * ellipsis ("…") + optional explanatory note. Shared by every page that loads
 * large village/site datasets so the loading animation is identical app-wide;
 * each page renders its own shimmer skeleton below this block to mirror the
 * real layout (see AnalyticsPage / HabitationsPage).
 */
import Icon from "./Icon.jsx";

export default function BrandedLoader({ title = "Loading data", note, className = "" }) {
  return (
    <div className={`flex flex-col items-center justify-center py-10 ${className}`}>
      <div className="relative w-14 h-14 mb-4">
        <div className="absolute inset-0 rounded-full border-2 border-[#1E2330] border-t-primary animate-spin" />
        <div className="absolute inset-[7px] rounded-[9px] bg-primary flex items-center justify-center">
          <Icon name="explore" className="text-surface-lowest font-bold text-[22px] icon-fill" />
        </div>
      </div>
      <p className="text-[13px] text-phase-text font-medium">
        {title}
        <span className="loading-dots" />
      </p>
      {note && (
        <p className="text-[11px] font-mono text-phase-text-secondary mt-1">{note}</p>
      )}
    </div>
  );
}
