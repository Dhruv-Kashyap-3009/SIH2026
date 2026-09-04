import { useEffect, useState } from "react";
import { Routes, Route, Navigate, Outlet } from "react-router-dom";
import Sidebar from "./components/layout/Sidebar.jsx";
import TopBar from "./components/layout/TopBar.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import HabitationsPage from "./pages/HabitationsPage.jsx";
import HabitationDetailPage from "./pages/HabitationDetailPage.jsx";
import PriorityPage from "./pages/PriorityPage.jsx";
import SitesPage from "./pages/SitesPage.jsx";
import CapacityPage from "./pages/CapacityPage.jsx";
import MapPage from "./pages/MapPage.jsx";
import AnalyticsPage from "./pages/AnalyticsPage.jsx";
import NotFoundPage from "./pages/NotFoundPage.jsx";
import HelpPage from "./pages/HelpPage.jsx";
import LoginPage from "./pages/LoginPage.jsx";
import LogoutPage from "./pages/LogoutPage.jsx";
import { SelectionProvider } from "./context/SelectionContext.jsx";
import { RefreshProvider } from "./context/RefreshContext.jsx";
import { AuthProvider, useAuth } from "./context/AuthContext.jsx";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { prefetchCompactVillages } from "./lib/villagesStore.js";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

/**
 * RequireAuth — layout-route guard: while the stored session is being validated
 * on startup it shows a loading screen (never flash the dashboard to a
 * logged-out user); unauthenticated visitors are redirected to /login; everyone
 * else renders the nested routes via <Outlet/>.
 */
function RequireAuth() {
  const { user, initializing } = useAuth();

  if (initializing) {
    return (
      <div className="h-screen w-full bg-surface flex items-center justify-center">
        <div className="flex items-center gap-3 text-on-surface-variant">
          <span className="w-4 h-4 border-2 border-primary border-t-transparent rounded-full animate-spin" />
          <span className="font-label-md text-label-md">Loading session…</span>
        </div>
      </div>
    );
  }

  if (!user) return <Navigate to="/" replace />; // “/” IS the sign-in page
  return <Outlet />;
}

/** The signed-in application shell — persistent sidebar + top bar around <Outlet/>. */
function AppLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  // Tier 2: kick off the one-and-only compact villages fetch at startup so the
  // map/table pages are instant once it lands — every page shares this cache.
  useEffect(() => {
    prefetchCompactVillages(queryClient);
  }, []);

  return (
    <SelectionProvider>
      <div className="flex h-screen overflow-hidden font-body-md">
        <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
        <div className="flex-1 md:ml-64 flex flex-col h-screen">
          <TopBar onMenuToggle={() => setSidebarOpen((p) => !p)} />
          <Outlet />
        </div>
      </div>
    </SelectionProvider>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
    <AuthProvider>
    <RefreshProvider>
      <Routes>
        {/* Public — no session needed. “/” is the sign-in page. */}
        <Route path="/" element={<LoginPage />} />
        <Route path="/logout" element={<LogoutPage />} />

        {/* Everything below the login gate */}
        <Route element={<RequireAuth />}>
          <Route element={<AppLayout />}>
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/villages" element={<HabitationsPage />} />
            <Route path="/villages/:id" element={<HabitationDetailPage />} />
            <Route path="/priority" element={<PriorityPage />} />
            <Route path="/sites" element={<SitesPage />} />
            <Route path="/capacity" element={<CapacityPage />} />
            <Route path="/map" element={<MapPage />} />
            <Route path="/analytics" element={<AnalyticsPage />} />
            <Route path="/help" element={<HelpPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Route>
        </Route>
      </Routes>
    </RefreshProvider>
    </AuthProvider>
    </QueryClientProvider>
  );
}
