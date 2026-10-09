import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { syncCollectorConfigOnLaunch } from "./pages/settings/collectorConfig";
import "./styles.css";

// 先把设置开关落盘到 config.json，第一次采集就能读到（Mac 启动时的 sync…OnLaunch）。
void syncCollectorConfigOnLaunch().finally(() => {
  ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  );
});
