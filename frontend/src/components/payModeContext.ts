import { createContext, useContext } from "react";

/** Opens Pay mode on a bill (see ``PayModeProvider``). Without a provider it does nothing. */
export type PayModeApi = { open: (billId: number) => void };

export const PayModeContext = createContext<PayModeApi>({ open: () => {} });

export const usePayMode = () => useContext(PayModeContext);
