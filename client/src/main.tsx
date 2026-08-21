// Entrée React — router + QueryClient + Tailwind import. Root mount #root.

import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import { LoginPage } from "./pages/LoginPage";
import { SessionsPage } from "./pages/SessionsPage";
import { SessionPage } from "./pages/SessionPage";
import { AlbumPage } from "./pages/AlbumPage";
import { useAmie } from "./store";

import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false, retry: 1 } },
});

/** Garde : redirige vers /login si aucun compte en session navigateur. */
function RequireUser({ children }: { children: React.ReactNode }) {
  const user = useAmie((s) => s.user);
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<App />}>
            <Route index element={<RootRedirect />} />
            <Route
              path="login"
              element={
                <AuthGate>
                  <LoginPage />
                </AuthGate>
              }
            />
            <Route
              path="sessions"
              element={
                <RequireUser>
                  <SessionsPage />
                </RequireUser>
              }
            />
            <Route
              path="session/:sid"
              element={
                <RequireUser>
                  <SessionPage />
                </RequireUser>
              }
            />
            <Route
              path="session/:sid/album"
              element={
                <RequireUser>
                  <AlbumPage />
                </RequireUser>
              }
            />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);

function RootRedirect() {
  const user = useAmie((s) => s.user);
  return <Navigate to={user ? "/sessions" : "/login"} replace />;
}

/** Si déjà connecté, /login renvoie vers la liste des sessions. */
function AuthGate({ children }: { children: React.ReactNode }) {
  const user = useAmie((s) => s.user);
  if (user) return <Navigate to="/sessions" replace />;
  return <>{children}</>;
}
