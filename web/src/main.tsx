import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Toaster } from "sonner";
import "./index.css";
import { LoginPage, SignupPage } from "./pages/auth";
import { ConsoleLayout } from "./pages/console/layout";
import { ConsoleOverview } from "./pages/console/overview";
import { ConsoleUsage } from "./pages/console/usage";
import { ConsoleBilling } from "./pages/console/billing";
import { ConsoleKeys } from "./pages/console/keys";
import { ConsoleTopup } from "./pages/console/topup";
import { ConsoleModels } from "./pages/console/models";
import { ConsoleDocs } from "./pages/console/docs";
import { AdminLayout } from "./pages/admin/layout";
import { AdminOverview } from "./pages/admin/overview";
import { AdminTenants } from "./pages/admin/tenants";
import { AdminTenantDetail } from "./pages/admin/tenant-detail";
import { AdminModels } from "./pages/admin/models";
import { AdminUpstreams } from "./pages/admin/upstreams";
import { AdminMonitoring } from "./pages/admin/monitoring";
import { AdminSettings } from "./pages/admin/settings";
import { AdminAdmins } from "./pages/admin/admins";
import { AdminLogs } from "./pages/admin/logs";
import { AdminAudit } from "./pages/admin/audit";
import { ConsoleLogs } from "./pages/console/logs";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/console" replace />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/signup" element={<SignupPage />} />
        <Route path="/admin/login" element={<LoginPage admin />} />
        <Route path="/console" element={<ConsoleLayout />}>
          <Route index element={<ConsoleOverview />} />
          <Route path="usage" element={<ConsoleUsage />} />
          <Route path="billing" element={<ConsoleBilling />} />
          <Route path="logs" element={<ConsoleLogs />} />
          <Route path="keys" element={<ConsoleKeys />} />
          <Route path="topup" element={<ConsoleTopup />} />
          <Route path="models" element={<ConsoleModels />} />
          <Route path="docs" element={<ConsoleDocs />} />
        </Route>
        <Route path="/admin" element={<AdminLayout />}>
          <Route index element={<AdminOverview />} />
          <Route path="tenants" element={<AdminTenants />} />
          <Route path="tenants/:id" element={<AdminTenantDetail />} />
          <Route path="models" element={<AdminModels />} />
          <Route path="upstreams" element={<AdminUpstreams />} />
          <Route path="monitoring" element={<AdminMonitoring />} />
          <Route path="settings" element={<AdminSettings />} />
          <Route path="admins" element={<AdminAdmins />} />
          <Route path="logs" element={<AdminLogs />} />
          <Route path="audit" element={<AdminAudit />} />
        </Route>
        <Route path="*" element={<Navigate to="/console" replace />} />
      </Routes>
    </BrowserRouter>
    <Toaster position="top-center" richColors closeButton />
  </React.StrictMode>,
);
