// True inside the /report print route: charts render as images, switches and buttons are left out.
import { createContext, useContext } from "react";

export const PrintModeContext = createContext(false);

export function usePrintMode(): boolean {
  return useContext(PrintModeContext);
}
