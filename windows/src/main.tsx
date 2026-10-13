import React from "react";
import ReactDOM from "react-dom/client";
import "./styles.css";
import { isQuickSurface } from "./lib/surface";
import { prepareLanguage } from "./lib/i18n";

// 界面立即渲染；首次采集和活跃统计仍等配置同步，保持隐私开关的启动顺序。
const languageReady = prepareLanguage();
const collectorReady = isQuickSurface ? languageReady : languageReady
  .then(() => import("./pages/settings/collectorConfig"))
  .then(({ syncCollectorConfigOnLaunch }) => syncCollectorConfigOnLaunch());
void collectorReady.catch(console.error);
const App = React.lazy(async () => { await languageReady; return import("./App"); });
ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
    <React.StrictMode>
      <React.Suspense fallback={<div className="page-loading" role="status"><span className="spinner" /><span>Tokei</span></div>}>
        <App collectorReady={collectorReady} />
      </React.Suspense>
    </React.StrictMode>,
);
