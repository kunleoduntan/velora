import * as React from "react";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { velora } from "./clientScripts";
import "./styles.css";

(window as unknown as { velora: typeof velora }).velora = velora;
(window as unknown as { React: typeof React }).React = React;
createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
