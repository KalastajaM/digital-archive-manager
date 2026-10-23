import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { installAppearance } from "./appearance";
import { RecoveryProvider } from "./components/Recovery";
import { ToastProvider } from "./components/Toasts";
import { UndoProvider } from "./components/UndoConfirm";
import { installOverflowTitles } from "./overflowTitles";
import "./theme.css";
import "./styles.css";

const client = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: true } },
});

installOverflowTitles();
installAppearance();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={client}>
      <ToastProvider>
        <UndoProvider>
          <RecoveryProvider>
            <BrowserRouter>
              <App />
            </BrowserRouter>
          </RecoveryProvider>
        </UndoProvider>
      </ToastProvider>
    </QueryClientProvider>
  </StrictMode>,
);
