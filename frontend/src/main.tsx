import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { installAppearance } from "./appearance";
import { PayModeProvider } from "./components/PayMode";
import { RecoveryProvider } from "./components/Recovery";
import { ToastProvider } from "./components/Toasts";
import { UndoProvider } from "./components/UndoConfirm";
import { installOverflowTitles } from "./overflowTitles";
import "./fonts.css";
import "./theme.css";
import "./styles.css";
import "./styles-new.css";

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
            <PayModeProvider>
              <BrowserRouter>
                <App />
              </BrowserRouter>
            </PayModeProvider>
          </RecoveryProvider>
        </UndoProvider>
      </ToastProvider>
    </QueryClientProvider>
  </StrictMode>,
);
