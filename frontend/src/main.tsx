import React, { lazy, Suspense } from "react";
import ReactDOM from "react-dom/client";
import "./styles.css";

const App = lazy(() => import("./App"));
const MaterialIdWebViewerApp = lazy(
  () => import("./components/MaterialIdWebViewerApp")
);
const NewPartWebViewerApp = lazy(
  () => import("./components/NewPartWebViewerApp")
);
const ReceiptHistoryWebViewerApp = lazy(
  () => import("./components/ReceiptHistoryWebViewerApp")
);

const requestedPage = new URLSearchParams(window.location.search).get("page");
const RootApp =
  requestedPage === "materialIdWebViewer"
      ? MaterialIdWebViewerApp
    : requestedPage === "newPartWebViewer"
      ? NewPartWebViewerApp
    : requestedPage === "receiptHistory"
      ? ReceiptHistoryWebViewerApp
    : App;

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Suspense
      fallback={
        <div
          style={{
            display: "grid",
            minHeight: "100vh",
            placeItems: "center",
            color: "#48647a",
            background: "#f4f8fb",
            fontSize: 13,
            fontWeight: 800
          }}
        >
          正在载入页面…
        </div>
      }
    >
      <RootApp />
    </Suspense>
  </React.StrictMode>
);
