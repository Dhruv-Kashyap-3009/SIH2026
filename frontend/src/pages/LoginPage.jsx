/**
 * LoginPage — full-screen sign-in (rendered outside the app shell).
 * Submits email/password to POST /api/auth/login via the AuthContext, then
 * hands off to the guarded dashboard. Shows a "signed out" notice when the
 * user just logged out (navigation state).
 */
import { useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import Icon from "../components/ui/Icon.jsx";
import { useAuth } from "../context/AuthContext.jsx";

export default function LoginPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const justSignedOut = location.state?.signedOut === true;

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  // Already authenticated → straight to the dashboard.
  if (user) return <Navigate to="/dashboard" replace />;

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email, password);
      navigate("/dashboard", { replace: true });
    } catch (err) {
      setError(err.message || "Login failed");
      setSubmitting(false);
    }
  }

  return (
    <div className="min-h-screen w-full bg-surface dark:bg-surface flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        {/* Brand */}
        <div className="flex flex-col items-center mb-8">
          <div className="w-14 h-14 rounded-[8px] bg-primary flex items-center justify-center mb-4">
            <Icon name="explore" className="text-surface-lowest font-bold text-2xl icon-fill" />
          </div>
          <h1 className="font-headline-md text-headline-md font-black text-primary">VYOMA</h1>
          <p className="font-label-md text-label-md text-on-surface-variant mt-1">
            Hazard Relocation Decision-Support Suite
          </p>
        </div>

        {/* Card */}
        <div className="bg-surface-container border border-border-subtle rounded-[8px] shadow-xl p-6">
          <h2 className="font-headline-sm text-headline-sm font-bold text-on-surface mb-1">
            Sign in
          </h2>
          <p className="font-label-sm text-label-sm text-on-surface-variant mb-5">
            Authorized users only — SIH 2026 demo credentials.
          </p>

          {justSignedOut && (
            <div className="mb-4 px-3 py-2 rounded-[4px] bg-secondary-container text-on-secondary-container font-label-sm text-label-sm">
              ✓ You have been signed out successfully.
            </div>
          )}
          {error && (
            <div className="mb-4 px-3 py-2 rounded-[4px] bg-error-container text-on-error-container font-label-sm text-label-sm">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <label className="flex flex-col gap-1.5">
              <span className="font-label-sm text-label-sm text-on-surface-variant">Email</span>
              <input
                type="email"
                required
                autoComplete="username"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="admin@vyoma.in"
                className="bg-surface-base border border-border-subtle rounded-[6px] px-3 py-2 font-body-md text-body-md text-on-surface placeholder:text-on-surface-variant/60 focus:outline-none focus:border-primary"
              />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="font-label-sm text-label-sm text-on-surface-variant">Password</span>
              <input
                type="password"
                required
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="bg-surface-base border border-border-subtle rounded-[6px] px-3 py-2 font-body-md text-body-md text-on-surface placeholder:text-on-surface-variant/60 focus:outline-none focus:border-primary"
              />
            </label>

            <button
              type="submit"
              disabled={submitting}
              className="mt-1 w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-[6px] bg-primary text-surface-lowest font-label-md text-label-md font-bold hover:opacity-90 transition-opacity disabled:opacity-60 disabled:cursor-wait"
            >
              {submitting ? (
                <>
                  <Icon name="sync" className="animate-spin text-[16px]" />
                  Signing in…
                </>
              ) : (
                <>
                  <Icon name="login" className="text-[16px]" />
                  Sign in
                </>
              )}
            </button>
          </form>
        </div>

        <p className="text-center mt-6 font-label-sm text-label-sm text-on-surface-variant">
          NE India Hazard Red Zone Platform · Smart India Hackathon 2026
        </p>
      </div>
    </div>
  );
}
