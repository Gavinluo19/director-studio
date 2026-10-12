import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import LegacyApp from "./App.tsx";
import LiveApp from "./v1/App.tsx";
import "./styles.css";
const App = window.location.pathname === "/b0" ? LegacyApp : LiveApp;
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
