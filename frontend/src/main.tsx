import React from "react";
import ReactDOM from "react-dom/client";
import { AllCommunityModule, ModuleRegistry } from "ag-grid-community";
import "ag-grid-community/styles/ag-grid.css";
import "ag-grid-community/styles/ag-theme-quartz.css";
import App from "./App";
import CustomerChatApp from "./components/CustomerChatApp";
import MaterialIdWebViewerApp from "./components/MaterialIdWebViewerApp";
import NewPartWebViewerApp from "./components/NewPartWebViewerApp";
import "./styles.css";

ModuleRegistry.registerModules([AllCommunityModule]);

const normalizedPath = window.location.pathname.replace(/\/+$/, "") || "/";
const requestedPage = new URLSearchParams(window.location.search).get("page");
const RootApp =
  normalizedPath === "/customer-chat"
    ? CustomerChatApp
    : requestedPage === "materialIdWebViewer"
      ? MaterialIdWebViewerApp
    : requestedPage === "newPartWebViewer"
      ? NewPartWebViewerApp
    : App;

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <RootApp />
  </React.StrictMode>
);
