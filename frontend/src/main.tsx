import React from "react";
import { createRoot } from "react-dom/client";
import { VisualizationApp } from "./visualization/VisualizationApp";
import "./styles.css";

createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <VisualizationApp />
  </React.StrictMode>,
);
