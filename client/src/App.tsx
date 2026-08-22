// Coquille applicative — bandeau supérieur + zone de contenu (Outlet).

import { Outlet, useNavigate } from "react-router-dom";
import { useAmie } from "./store";

export default function App() {
  const user = useAmie((s) => s.user);
  const setUser = useAmie((s) => s.setUser);
  const setPassword = useAmie((s) => s.setPassword);
  const reset = useAmie((s) => s.reset);
  const navigate = useNavigate();

  function logout() {
    setUser("");
    setPassword("");
    reset();
    navigate("/login");
  }

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b border-rose-900/40 bg-[#24101c]/80 px-4 py-3 backdrop-blur">
        <div className="flex items-center gap-2">
          <span className="text-xl">💌</span>
          <h1 className="bg-gradient-to-r from-rose-300 to-fuchsia-300 bg-clip-text text-lg font-semibold text-transparent">
            Ami(e) IA
          </h1>
        </div>
        {user && (
          <div className="flex items-center gap-3">
            <span className="text-sm text-rose-200/70">{user}</span>
            <button
              onClick={logout}
              className="rounded-md border border-rose-800/60 px-3 py-1 text-sm text-rose-200 transition hover:bg-rose-900/40"
            >
              Déconnexion
            </button>
          </div>
        )}
      </header>
      <main className="min-h-0 flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  );
}
