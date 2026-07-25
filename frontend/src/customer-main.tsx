import React from "react";
import ReactDOM from "react-dom/client";
import CustomerChatApp from "./components/CustomerChatApp";
import "./styles.css";
import "./customer-portal.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <CustomerChatApp />
  </React.StrictMode>
);
