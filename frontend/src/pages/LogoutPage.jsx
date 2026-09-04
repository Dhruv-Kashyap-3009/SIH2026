/**
 * LogoutPage — ends the session and returns to the login screen.
 *
 * Rendered OUTSIDE the authenticated shell so there is no redirect race: on
 * mount it clears the stored session (AuthContext.logout) and navigates to
 * /login with a `signedOut` flag so LoginPage can show a confirmation notice.
 */
import { useEffect } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import Icon from "../components/ui/Icon.jsx";
import { useAuth } from "../context/AuthContext.jsx";

export default function LogoutPage() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    logout();
    const t = setTimeout(
      () => navigate("/login", { replace: true, state: { signedOut: true } }),
      400
    );
    return () => clearTimeout(t);
  }, [logout, navigate]);

  // If the user is still signed in (e.g. the effect hasn't run yet) we stay
  // here; once logout() flips state this component's parent (the public route)
  // keeps showing it until the navigation fires. Safe no-op for guests.
  if (!user) {
    // Fallback in case navigation is blocked — never strand the user.
    return <Navigate to="/login" replace state={{ signedOut: true }} />;
  }

  return (
    <main className="flex-1 overflow-y-auto bg-phase-bg p-6 flex items-center justify-center">
      <div className="text-center max-w-md">
        <div className="w-16 h-16 rounded-full bg-phase-elevated border border-[#1E2330] flex items-center justify-center mx-auto mb-4">
          <Icon name="sync" className="text-[28px] text-phase-text-secondary animate-spin" />
        </div>
        <h2 className="text-[20px] font-semibold text-phase-text mb-2">Signing you out…</h2>
        <p className="text-[14px] text-phase-text-secondary">
          Clearing your session and returning to the login page.
        </p>
      </div>
    </main>
  );
}
